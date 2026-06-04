export type TurfConfiguration = {
  code: string;
  displayName: string;
  availableFields: Array<'SMALL' | 'MEDIUM' | 'LARGE'>;
  supportedDivisions: string[];
  maxFieldsPerWave: number;
  schedulingNote: string;
};

export const APPROVED_TURF_CONFIGURATIONS: TurfConfiguration[] = [
  {
    code: 'THREE_SMALL',
    displayName: 'Three Small Fields',
    availableFields: ['SMALL', 'SMALL', 'SMALL'],
    supportedDivisions: ['Coed K-1', 'Coed 2-3', 'Girls K-2'],
    maxFieldsPerWave: 3,
    schedulingNote: 'Best for waves made entirely of small-field divisions; unused small slots may remain open.',
  },
  {
    code: 'TWO_SMALL_ONE_MEDIUM',
    displayName: 'Two Small Fields + One Medium Field',
    availableFields: ['SMALL', 'SMALL', 'MEDIUM'],
    supportedDivisions: ['Coed K-1', 'Coed 2-3', 'Girls K-2', 'Coed 4-5', 'Girls 3-5'],
    maxFieldsPerWave: 3,
    schedulingNote: 'Supports mixed small- and medium-field waves; large-field games require a different approved configuration.',
  },
  {
    code: 'TWO_MEDIUM',
    displayName: 'Two Medium Fields',
    availableFields: ['MEDIUM', 'MEDIUM'],
    supportedDivisions: ['Coed 4-5', 'Girls 3-5'],
    maxFieldsPerWave: 2,
    schedulingNote: 'Best for medium-field waves; small and large games are not compatible with this configuration.',
  },
  {
    code: 'ONE_SMALL_ONE_LARGE',
    displayName: 'One Small Field + One Large Field',
    availableFields: ['SMALL', 'LARGE'],
    supportedDivisions: ['Coed K-1', 'Coed 2-3', 'Girls K-2', 'Coed 6-7', 'Coed 8', 'Girls 6-8'],
    maxFieldsPerWave: 2,
    schedulingNote: 'Supports one small-field game and one large-field game in the same wave; medium games require a different approved configuration.',
  },
];

export const APPROVED_TURF_CONFIGURATION_CODES = APPROVED_TURF_CONFIGURATIONS.map((config) => config.code);

export const isApprovedTurfConfigurationCode = (code?: string | null) => Boolean(code && APPROVED_TURF_CONFIGURATION_CODES.includes(code));

export const turfConfigurationLabel = (code?: string | null) => {
  const config = APPROVED_TURF_CONFIGURATIONS.find((item) => item.code === code);
  return config ? `${config.code} — ${config.displayName}` : code || 'Unknown layout';
};

export const turfAvailableFieldsLabel = (fields: TurfConfiguration['availableFields']) => fields.map((field) => `${field.charAt(0)}${field.slice(1).toLowerCase()} Field`).join(' + ');
