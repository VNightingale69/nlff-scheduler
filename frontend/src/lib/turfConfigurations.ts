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
    code: 'ONE_LARGE_ONE_SMALL',
    displayName: 'One Large Field + One Small Field',
    availableFields: ['SMALL', 'LARGE'],
    supportedDivisions: ['Coed K-1', 'Coed 2-3', 'Girls K-2', 'Coed 6-7', 'Coed 8', 'Girls 6-8'],
    maxFieldsPerWave: 2,
    schedulingNote: 'Canonical league-wide Turf Stadium layout: one Large game and one Small game may run simultaneously.',
  },
];

export const APPROVED_TURF_CONFIGURATION_CODES = APPROVED_TURF_CONFIGURATIONS.map((config) => config.code);

export const STANDARD_TURF_CONFIGURATION_CODES = ['ONE_LARGE_ONE_SMALL'];

export const turfConfigurationsForHost = (hostName?: string | null, organizationName?: string | null) => {
  void hostName;
  void organizationName;
  return APPROVED_TURF_CONFIGURATIONS;
};

export const isApprovedTurfConfigurationCode = (code?: string | null) => Boolean(code && APPROVED_TURF_CONFIGURATION_CODES.includes(code));

export const turfConfigurationLabel = (code?: string | null) => {
  const config = APPROVED_TURF_CONFIGURATIONS.find((item) => item.code === code);
  return config ? `${config.code} — ${config.displayName}` : code || 'Unknown layout';
};

export const turfAvailableFieldsLabel = (fields: TurfConfiguration['availableFields']) => fields.map((field) => `${field.charAt(0)}${field.slice(1).toLowerCase()} Field`).join(' + ');
