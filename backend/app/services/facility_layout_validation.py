"""Resolve and validate supported facility layouts for scheduled kickoff waves."""
from collections import Counter

from app.models import Field, FieldConfigurationMember, HostLocationConfiguration, TimeslotFieldConfiguration


SIZES = ('SMALL', 'MEDIUM', 'LARGE')


def _size(value):
    value = str(value or '').strip().upper()
    return value if value in SIZES else None


def _capacity(configuration):
    return {size: int(getattr(configuration, f'{size.lower()}_field_count', 0) or 0) for size in SIZES}


def validate_timeslot_demands(demands, available_layouts):
    """Validate physical capacity independently for every host kickoff wave.

    ``demands`` maps ``(date, host, kickoff)`` to size counts and
    ``available_layouts`` maps the same key to one or more allowed capacity
    dictionaries.  A later kickoff is deliberately a different key, so the
    same physical field can be reused.  A wave is valid only when one complete
    allowed layout can accommodate its simultaneous combination.
    """
    shortages = []
    peak = {size: 0 for size in SIZES}
    for key, raw_demand in demands.items():
        demand = {size: int(raw_demand.get(size, 0) or 0) for size in SIZES}
        for size in SIZES:
            peak[size] = max(peak[size], demand[size])
        layouts = [
            {size: int(layout.get(size, 0) or 0) for size in SIZES}
            for layout in available_layouts.get(key, [])
        ]
        if any(all(layout[size] >= demand[size] for size in SIZES) for layout in layouts):
            continue
        best = max(layouts, key=lambda layout: sum(min(layout[size], demand[size]) for size in SIZES), default={size: 0 for size in SIZES})
        individually_supported = bool(layouts) and all(
            max((layout[size] for layout in layouts), default=0) >= demand[size] for size in SIZES
        )
        shortages.append({
            'key': key,
            'demand': demand,
            'available_layouts': layouts,
            'shortage_by_size': {size: max(demand[size] - best.get(size, 0), 0) for size in SIZES},
            'unsupported_combination': individually_supported,
        })
    return {'valid': not shortages, 'peak_by_size': peak, 'shortages': shortages}


def select_supported_layout(db, host_id, game_date, kickoff, required_sizes, *, persist=False):
    """Select one explicitly configured layout satisfying the whole wave.

    Considering all games together is what makes a one-Large layout consume
    both logical Medium positions instead of merely changing one field label.
    """
    demand = Counter(filter(None, (_size(value) for value in required_sizes)))
    existing = db.query(TimeslotFieldConfiguration).filter_by(
        host_location_id=host_id, configuration_date=game_date, kickoff_time=kickoff,
    ).first()
    configurations = db.query(HostLocationConfiguration).filter_by(
        host_location_id=host_id, is_active=True,
    ).order_by(HostLocationConfiguration.configuration_name).all()
    supported = [configuration for configuration in configurations
                 if validate_timeslot_demands(
                     {(game_date, host_id, kickoff): demand},
                     {(game_date, host_id, kickoff): [_capacity(configuration)]},
                 )['valid']]
    if existing:
        selected = next((item for item in configurations if item.id == existing.configuration_id), None)
        return existing, selected, bool(selected and selected in supported)
    if not supported:
        return None, None, False
    # Prefer the tightest valid footprint, making the sole satisfying alternate
    # deterministic while avoiding needless reconfiguration where possible.
    selected = min(supported, key=lambda item: (sum(_capacity(item).values()), item.configuration_name))
    override = None
    if persist:
        override = TimeslotFieldConfiguration(host_location_id=host_id, configuration_id=selected.id,
                                              configuration_date=game_date, kickoff_time=kickoff)
        db.add(override); db.flush()
    return override, selected, True


def layout_label(configuration):
    if not configuration:
        return None
    parts = [f'{count} {size.title()}' for size, count in _capacity(configuration).items() if count]
    return ' + '.join(parts) or configuration.configuration_name


def validate_field_combination(db, host_id, field_ids):
    """Return whether exact physical fields are a subset of one active layout.

    A missing layout is treated as the legacy all-active-fields layout so older
    facilities remain schedulable while administrators migrate their setup.
    """
    used = {field_id for field_id in field_ids if field_id}
    configurations = db.query(HostLocationConfiguration).filter_by(host_location_id=host_id, is_active=True).all()
    layouts = []
    for configuration in configurations:
        members = {row.field_id for row in db.query(FieldConfigurationMember).filter_by(field_configuration_id=configuration.id)}
        if members:
            layouts.append((configuration, members))
    if not layouts:
        active = {row.id for row in db.query(Field.id).filter_by(host_location_id=host_id, is_active=True)
                  if row.deleted_at is None}
        return used.issubset(active), [], active
    matching = [configuration for configuration, members in layouts if used.issubset(members)]
    return bool(matching), [configuration.configuration_name for configuration, _members in layouts], used
