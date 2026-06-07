"""League-approved turf stadium configuration definitions."""
from __future__ import annotations

FIELD_SIZE_SMALL = 'SMALL'
FIELD_SIZE_MEDIUM = 'MEDIUM'
FIELD_SIZE_LARGE = 'LARGE'
FIELD_SIZE_ORDER = (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM, FIELD_SIZE_LARGE)

INVALID_TURF_CONFIGURATION_MESSAGE = (
    'Invalid turf configuration. Turf stadium locations may only use '
    'THREE_SMALL, TWO_SMALL_ONE_MEDIUM, TWO_MEDIUM, ONE_SMALL_ONE_LARGE, or ONE_LARGE. TWO_LARGE, Large Field 2, Medium+Large, and Two Small+Large are not valid on one turf surface.'
)

APPROVED_TURF_CONFIGURATIONS: tuple[dict[str, object], ...] = (
    {
        'code': 'THREE_SMALL',
        'displayName': 'Three Small Fields',
        'availableFields': (FIELD_SIZE_SMALL, FIELD_SIZE_SMALL, FIELD_SIZE_SMALL),
        'supportedFieldSizes': (FIELD_SIZE_SMALL,),
        'supportedDivisions': ('Coed K-1', 'Coed 2-3', 'Girls K-2'),
        'maxFieldsPerWave': 3,
        'schedulingNote': 'Best for waves made entirely of small-field divisions; unused small slots may remain open.',
        'spaceUsedYards': 100,
        'remainingYards': 20,
    },
    {
        'code': 'TWO_SMALL_ONE_MEDIUM',
        'displayName': 'Two Small Fields + One Medium Field',
        'availableFields': (FIELD_SIZE_SMALL, FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM),
        'supportedFieldSizes': (FIELD_SIZE_SMALL, FIELD_SIZE_MEDIUM),
        'supportedDivisions': ('Coed K-1', 'Coed 2-3', 'Girls K-2', 'Coed 4-5', 'Girls 3-5'),
        'maxFieldsPerWave': 3,
        'schedulingNote': 'Supports mixed small- and medium-field waves; large-field games require a different approved configuration.',
        'spaceUsedYards': 120,
        'remainingYards': 0,
    },
    {
        'code': 'TWO_MEDIUM',
        'displayName': 'Two Medium Fields',
        'availableFields': (FIELD_SIZE_MEDIUM, FIELD_SIZE_MEDIUM),
        'supportedFieldSizes': (FIELD_SIZE_MEDIUM,),
        'supportedDivisions': ('Coed 4-5', 'Girls 3-5'),
        'maxFieldsPerWave': 2,
        'schedulingNote': 'Best for medium-field waves; small and large games are not compatible with this configuration.',
        'spaceUsedYards': 110,
        'remainingYards': 10,
    },
    {
        'code': 'ONE_SMALL_ONE_LARGE',
        'displayName': 'One Small Field + One Large Field',
        'availableFields': (FIELD_SIZE_SMALL, FIELD_SIZE_LARGE),
        'supportedFieldSizes': (FIELD_SIZE_SMALL, FIELD_SIZE_LARGE),
        'supportedDivisions': ('Coed K-1', 'Coed 2-3', 'Girls K-2', 'Coed 6-7', 'Coed 8', 'Girls 6-8'),
        'maxFieldsPerWave': 2,
        'schedulingNote': 'Supports one small-field game and one large-field game in the same wave; medium games require a different approved configuration.',
        'spaceUsedYards': 90,
        'remainingYards': 30,
    },

    {
        'code': 'ONE_LARGE',
        'displayName': 'One Large Field',
        'availableFields': (FIELD_SIZE_LARGE,),
        'supportedFieldSizes': (FIELD_SIZE_LARGE,),
        'supportedDivisions': ('Coed 6-7', 'Coed 8', 'Girls 6-8'),
        'maxFieldsPerWave': 1,
        'schedulingNote': 'Supports one large-field game only; Small Field 1 may be paired with Large Field 1 only under ONE_SMALL_ONE_LARGE.',
        'spaceUsedYards': 70,
        'remainingYards': 50,
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
