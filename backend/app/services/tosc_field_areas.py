"""Canonical, independently configurable playing areas at Antioch TOSC."""
from sqlalchemy.orm import Session

from app.models import FieldConfigurationOption, HostLocation, HostLocationConfiguration, PhysicalFieldArea

TOSC_LOCATION_NAMES = {"TIM OSMOND SPORTS COMPLEX", "ANTIOCH - TIM OSMOND SPORTS COMPLEX", "ANTIOCH - TOSC"}
TOSC_ORGANIZATIONS = {"ANTIOCH", "ANTIOCH VIKINGS"}
COMMON_LAYOUTS = (("1 Large + 1 Small", 1, 0, 1), ("2 Medium", 0, 2, 0), ("3 Small", 0, 0, 3))
TOSC_AREAS = {
    "Football Field 1": COMMON_LAYOUTS,
    "Football Field 2": COMMON_LAYOUTS,
    "Soccer Field": COMMON_LAYOUTS + (("1 Medium + 1 Small", 0, 1, 1), ("1 Large", 1, 0, 0)),
}


def is_antioch_tosc(host: HostLocation) -> bool:
    return (str(host.name or "").strip().upper() in TOSC_LOCATION_NAMES
            and str(getattr(host.organization, "name", "") or "").strip().upper() in TOSC_ORGANIZATIONS)


def ensure_tosc_physical_areas(db: Session, host: HostLocation) -> bool:
    """Idempotently replace site-wide layouts with area-scoped capabilities."""
    if not is_antioch_tosc(host):
        return False
    changed = False
    if host.surface_type != "GRASS_FIELD":
        host.surface_type = "GRASS_FIELD"; changed = True
    for legacy in db.query(HostLocationConfiguration).filter_by(host_location_id=host.id).all():
        if legacy.is_active or not legacy.is_legacy:
            legacy.is_active = False; legacy.is_legacy = True; changed = True
    existing_areas = {area.name: area for area in db.query(PhysicalFieldArea).filter_by(host_location_id=host.id)}
    for name, layouts in TOSC_AREAS.items():
        area = existing_areas.get(name)
        if area is None:
            area = PhysicalFieldArea(host_location_id=host.id, name=name, field_space_type="FULL_SIZE_FIELD",
                                     supports_dynamic_configuration=True, is_active=True)
            db.add(area); db.flush(); changed = True
        area.is_active = True; area.supports_dynamic_configuration = True
        area.notes = "Approximately 120 yards × 75 yards" if name == "Soccer Field" else "Regulation football field"
        expected = {layout[0] for layout in layouts}
        for old in db.query(FieldConfigurationOption).filter_by(physical_field_area_id=area.id).all():
            if old.name not in expected and old.is_active:
                old.is_active = False; changed = True
        options = {option.name: option for option in db.query(FieldConfigurationOption).filter_by(physical_field_area_id=area.id)}
        for layout_name, large, medium, small in layouts:
            option = options.get(layout_name)
            if option is None:
                option = FieldConfigurationOption(physical_field_area_id=area.id, name=layout_name)
                db.add(option); changed = True
            option.configuration_name = layout_name; option.surface_type = "GRASS_FIELD"
            option.large_field_count, option.medium_field_count, option.small_field_count = large, medium, small
            option.fifty_three_yard_capacity, option.thirty_yard_capacity = large, small
            option.is_active = True
    return changed
