"""League-approved turf stadium configuration definitions."""
from __future__ import annotations

FIELD_SIZE_SMALL = 'SMALL'
FIELD_SIZE_MEDIUM = 'MEDIUM'
FIELD_SIZE_LARGE = 'LARGE'
FIELD_SIZE_ORDER = (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM, FIELD_SIZE_LARGE)

INVALID_TURF_CONFIGURATION_MESSAGE = (
    'Invalid turf configuration. Turf stadium locations may only use '
    'ONE_LARGE_ONE_SMALL (one Large field and one Small field).'
)

APPROVED_TURF_CONFIGURATIONS: tuple[dict[str, object], ...] = (
    {
        'code': 'ONE_LARGE_ONE_SMALL',
        'displayName': 'One Large Field + One Small Field',
        'availableFields': (FIELD_SIZE_SMALL, FIELD_SIZE_LARGE),
        'supportedFieldSizes': (FIELD_SIZE_SMALL, FIELD_SIZE_LARGE),
        'supportedDivisions': ('Coed K-1', 'Coed 2-3', 'Girls K-2', 'Coed 6-7', 'Coed 8', 'Girls 6-8'),
        'maxFieldsPerWave': 2,
        'schedulingNote': 'Canonical league-wide Turf Stadium layout: one Large game and one Small game may run simultaneously.',
        'spaceUsedYards': 90,
        'remainingYards': 30,
    },
)

APPROVED_TURF_CONFIGURATIONS_BY_CODE = {str(config['code']): config for config in APPROVED_TURF_CONFIGURATIONS}
APPROVED_TURF_CONFIGURATION_CODES = tuple(config['code'] for config in APPROVED_TURF_CONFIGURATIONS)

# Read-only compatibility aliases for names historically used for the same approved footprints.
# Old unauthorized layouts intentionally do not appear here and must be rejected/cleared.
BACKWARD_COMPATIBLE_TURF_CONFIGURATION_ALIASES: dict[str, str] = {}


def normalize_turf_configuration_code(value: str | None) -> str:
    normalized = str(value or '').strip().upper().replace('-', '_').replace(' ', '_')
    return BACKWARD_COMPATIBLE_TURF_CONFIGURATION_ALIASES.get(normalized, normalized)


def approved_turf_configuration_metadata(value: str | None) -> dict[str, object] | None:
    return APPROVED_TURF_CONFIGURATIONS_BY_CODE.get(normalize_turf_configuration_code(value))


def turf_configuration_counts(config: dict[str, object]) -> dict[str, int]:
    fields = tuple(config.get('availableFields') or ())
    return {size: fields.count(size) for size in FIELD_SIZE_ORDER}


def turf_configuration_legacy_metadata() -> dict[str, dict[str, object]]:
    return {
        str(config['code']): {
            'configuration_name': config['displayName'],
            'display_name': config['displayName'],
            'available_fields': config['availableFields'],
            'supported_field_sizes': config['supportedFieldSizes'],
            'supported_divisions': config['supportedDivisions'],
            'max_fields_per_wave': config['maxFieldsPerWave'],
            'scheduling_note': config['schedulingNote'],
            'space_used_yards': config['spaceUsedYards'],
            'remaining_yards': config['remainingYards'],
            'counts': turf_configuration_counts(config),
        }
        for config in APPROVED_TURF_CONFIGURATIONS
    }
