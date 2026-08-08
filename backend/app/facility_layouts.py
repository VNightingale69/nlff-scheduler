"""Canonical facility-specific field layouts shared by scheduling workflows."""

JOHNSBURG_ORGANIZATION_NAMES = frozenset({'JOHNSBURG', 'JOHNSBURG SKYHAWKS'})
JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION = {
    'JOHNSBURG STADIUM': frozenset({'ONE_LARGE_ONE_MEDIUM'}),
    'HILLER PARK': frozenset({'FOUR_SMALL'}),
    'HILLER STADIUM': frozenset({'TWO_MEDIUM'}),
}
JOHNSBURG_FIELD_TEMPLATES_BY_LOCATION = {
    'JOHNSBURG STADIUM': [('Field 1', 'LARGE'), ('Field 3', 'MEDIUM')],
    'HILLER PARK': [(f'Field {index}', 'SMALL') for index in range(1, 5)],
    'HILLER STADIUM': [('Field 1', 'MEDIUM'), ('Field 3', 'MEDIUM')],
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
        return list(JOHNSBURG_FIELD_TEMPLATES_BY_LOCATION[location])
    return None
