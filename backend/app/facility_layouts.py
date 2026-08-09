"""Canonical facility-specific field layouts shared by scheduling workflows."""

JOHNSBURG_ORGANIZATION_NAMES = frozenset({'JOHNSBURG', 'JOHNSBURG SKYHAWKS'})
JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION = {
    location: frozenset({'ONE_LARGE_ONE_SMALL'})
    for location in ('JOHNSBURG STADIUM', 'HILLER PARK', 'HILLER STADIUM')
}
JOHNSBURG_FIELD_TEMPLATES_BY_LOCATION_AND_LAYOUT = {
    (location, 'ONE_LARGE_ONE_SMALL'): [('Large Field', 'LARGE'), ('Small Field', 'SMALL')]
    for location in JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION
}

# Backwards-compatible aggregate used by administration/read models.  Layout
# validation must use the layout-specific mapping above instead.
JOHNSBURG_FIELD_TEMPLATES_BY_LOCATION = {
    location: list(dict.fromkeys(
        field for (candidate, _layout), fields in JOHNSBURG_FIELD_TEMPLATES_BY_LOCATION_AND_LAYOUT.items()
        if candidate == location for field in fields
    ))
    for location in JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION
}


def normalized_layout_code(value) -> str:
    return str(value or '').strip().upper().replace('-', '_').replace(' ', '_')


def johnsburg_location_name(host) -> str | None:
    organization_name = str(getattr(getattr(host, 'organization', None), 'name', '') or '').strip().upper()
    location_name = str(getattr(host, 'name', '') or '').strip().upper()
    if organization_name in JOHNSBURG_ORGANIZATION_NAMES and location_name in JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION:
        return location_name
    return None


def johnsburg_field_templates(host, configuration_name) -> list[tuple[str, str]] | None:
    """Return a configured Johnsburg layout, or None for a non-Johnsburg host/layout."""
    location = johnsburg_location_name(host)
    if location and normalized_layout_code(configuration_name) in JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION[location]:
        return list(JOHNSBURG_FIELD_TEMPLATES_BY_LOCATION_AND_LAYOUT.get(
            (location, normalized_layout_code(configuration_name)), []
        ))
    return None
