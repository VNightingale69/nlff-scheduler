"""Canonical division-to-field-size rules shared by scheduling workflows."""

SMALL, MEDIUM, LARGE = 'SMALL', 'MEDIUM', 'LARGE'


def normalize_field_size(value: object) -> str | None:
    text = str(value or '').strip().upper().replace('-', '_').replace(' ', '_')
    if text in {SMALL, MEDIUM, LARGE}:
        return text
    if text in {'THIRTY_YARD_WIDTH', '30_YARD_WIDTH', '30'}:
        return SMALL
    if text in {'FORTY_YARD_WIDTH', '40_YARD_WIDTH', '40'}:
        return MEDIUM
    if text in {'FIFTY_THREE_YARD_WIDTH', '53_YARD_WIDTH', '53'}:
        return LARGE
    return None


CANONICAL_DIVISION_FIELD_TYPES = {
    'COED:K1': SMALL, 'COED:K1ST': SMALL,
    'COED:23': SMALL, 'COED:2ND3RD': SMALL,
    'COED:45': MEDIUM, 'COED:4TH5TH': MEDIUM,
    'COED:67': LARGE, 'COED:6TH7TH': LARGE,
    'COED:8': LARGE, 'COED:8TH': LARGE,
    'GIRLS:K2': SMALL, 'GIRLS:K1ST': SMALL,
    'GIRLS:23': SMALL, 'GIRLS:2ND3RD': SMALL,
    'GIRLS:35': MEDIUM, 'GIRLS:45': MEDIUM, 'GIRLS:4TH5TH': MEDIUM,
    'GIRLS:67': LARGE, 'GIRLS:6TH7TH': LARGE,
    'GIRLS:68': LARGE, 'GIRLS:6TH7TH8TH': LARGE,
}


def required_field_type_for_division(division: object | None) -> str:
    """Use the stored league rule first, then the canonical legacy-name map."""
    if division is None:
        return SMALL
    configured = normalize_field_size(getattr(division, 'required_field_layout_type', None))
    if configured:
        return configured
    group = str(getattr(division, 'division_group', '') or '').upper()
    name = ''.join(ch for ch in str(getattr(division, 'name', '') or '').upper() if ch.isalnum())
    return CANONICAL_DIVISION_FIELD_TYPES.get(f'{group}:{name}', SMALL)
