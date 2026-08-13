"""Resolve and validate supported facility layouts for scheduled kickoff waves."""
from collections import Counter

from sqlalchemy.orm import selectinload

from app.models import Field, FieldConfigurationMember, HostLocation, HostLocationConfiguration, TimeslotFieldConfiguration
from app.turf_configurations import APPROVED_TURF_CONFIGURATIONS, turf_configuration_counts


SIZES = ('SMALL', 'MEDIUM', 'LARGE')


def _size(value):
    value = str(value or '').strip().upper()
    return value if value in SIZES else None


def _capacity(configuration):
    return {size: int(getattr(configuration, f'{size.lower()}_field_count', 0) or 0) for size in SIZES}


def active_supported_layouts_query(db, host_location_id):
    """Build the uncached authoritative query shared by API and schedulers."""
    return (
        db.query(HostLocationConfiguration)
        .options(
            selectinload(HostLocationConfiguration.members)
            .selectinload(FieldConfigurationMember.field)
        )
        .filter(
            HostLocationConfiguration.host_location_id == host_location_id,
            HostLocationConfiguration.is_active.is_(True),
        )
    )


def get_active_supported_layouts(db, host_location_id):
    """Load every current alternative layout for one host location.

    League-approved definitions are authoritative for managed turf stadiums;
    persisted configurations remain authoritative for other facility types.
    This intentionally does not inspect generated slots, turf waves, or a
    default timeslot selection. Persisted members and fields are eagerly loaded.
    """
    host = db.query(HostLocation).filter(HostLocation.id == host_location_id).first()
    if host and (host.surface_type or '').upper() == 'TURF_STADIUM':
        # Approved layouts describe capability. They must not disappear because
        # a legacy row is inactive or only the most recently generated layout
        # happened to be persisted.
        existing = {
            str(row.configuration_name or '').strip().upper(): row
            for row in db.query(HostLocationConfiguration).filter(
                HostLocationConfiguration.host_location_id == host_location_id,
            ).all()
        }
        layouts = []
        for sort_order, metadata in enumerate(APPROVED_TURF_CONFIGURATIONS):
            code = str(metadata['code'])
            configuration = existing.get(code) or HostLocationConfiguration(
                host_location_id=host_location_id,
                configuration_name=code,
                is_active=True,
            )
            counts = turf_configuration_counts(metadata)
            configuration.small_field_count = counts['SMALL']
            configuration.medium_field_count = counts['MEDIUM']
            configuration.large_field_count = counts['LARGE']
            configuration.sort_order = sort_order
            layouts.append(configuration)
        return layouts
    return (
        active_supported_layouts_query(db, host_location_id)
        .order_by(
            HostLocationConfiguration.sort_order,
            HostLocationConfiguration.configuration_name,
            HostLocationConfiguration.id,
        )
        .all()
    )


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
    configurations = get_active_supported_layouts(db, host_id)
    supported = [configuration for configuration in configurations
                 if validate_timeslot_demands(
                     {(game_date, host_id, kickoff): demand},
                     {(game_date, host_id, kickoff): [_capacity(configuration)]},
                 )['valid']]
    if existing:
        selected = next((item for item in configurations if item.id == existing.configuration_id), None)
        if selected:
            # An active, time-specific row is an explicit physical-layout lock.
            # It is the only case where one layout may conclusively block a
            # wave.  A row pointing to a retired layout is historical generated
            # metadata, however, and must not hide current alternatives.
            return existing, selected, selected in supported
    if not supported:
        return None, None, False
    previous_code = None
    if game_date is not None and kickoff is not None:
        previous = (
            db.query(TimeslotFieldConfiguration)
            .join(HostLocationConfiguration)
            .filter(
                TimeslotFieldConfiguration.host_location_id == host_id,
                TimeslotFieldConfiguration.configuration_date == game_date,
                TimeslotFieldConfiguration.kickoff_time < kickoff,
                HostLocationConfiguration.is_active.is_(True),
            )
            .order_by(TimeslotFieldConfiguration.kickoff_time.desc())
            .first()
        )
        if previous and previous.configuration:
            previous_code = previous.configuration.configuration_name

    demand_total = sum(demand.values())
    demand_exact = {size: int(demand.get(size, 0)) for size in SIZES}
    selected = min(supported, key=lambda item: (
        0 if _capacity(item) == demand_exact else 1,
        sum(_capacity(item).values()) - demand_total,
        0 if item.configuration_name == previous_code else 1,
        item.configuration_name,
    ))
    override = None
    if persist and selected.id is not None:
        if existing:
            existing.configuration_id = selected.id
            override = existing
        else:
            override = TimeslotFieldConfiguration(host_location_id=host_id, configuration_id=selected.id,
                                                  configuration_date=game_date, kickoff_time=kickoff)
            db.add(override)
        db.flush()
    return override, selected, True


def active_layout_capacities(db, host_id):
    """Return the current host-scoped layouts considered by validation."""
    configurations = get_active_supported_layouts(db, host_id)
    return [
        {'id': str(configuration.id) if configuration.id else None, 'code': configuration.configuration_name, 'capacity': _capacity(configuration)}
        for configuration in configurations
    ]


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
    configurations = get_active_supported_layouts(db, host_id)
    layouts = []
    for configuration in configurations:
        members = {
            row.field_id
            for row in db.query(FieldConfigurationMember)
            .join(Field, Field.id == FieldConfigurationMember.field_id)
            .filter(
                FieldConfigurationMember.field_configuration_id == configuration.id,
                Field.is_active.is_(True),
                Field.deleted_at.is_(None),
            )
        }
        if members:
            layouts.append((configuration, members))
    if not layouts:
        active = {
            row.id
            for row in db.query(Field.id).filter(
                Field.host_location_id == host_id,
                Field.is_active.is_(True),
                Field.deleted_at.is_(None),
            )
        }
        return used.issubset(active), [], active
    matching = [configuration for configuration, members in layouts if used.issubset(members)]
    return bool(matching), [configuration.configuration_name for configuration, _members in layouts], used
