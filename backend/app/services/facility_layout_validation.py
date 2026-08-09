"""Resolve and validate supported facility layouts for scheduled kickoff waves."""
from collections import Counter

from app.models import HostLocationConfiguration, TimeslotFieldConfiguration


SIZES = ('SMALL', 'MEDIUM', 'LARGE')


def _size(value):
    value = str(value or '').strip().upper()
    return value if value in SIZES else None


def _capacity(configuration):
    return {size: int(getattr(configuration, f'{size.lower()}_field_count', 0) or 0) for size in SIZES}


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
                 if all(_capacity(configuration)[size] >= count for size, count in demand.items())]
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
