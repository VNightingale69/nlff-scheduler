export type FieldType = 'small' | 'medium' | 'large';
export type ExtraPointRule = 'none' | 'optional_1_or_2';

export type DivisionScoringInfo = {
  fieldType: FieldType;
  touchdownPoints: 1 | 6;
  extraPointRule: ExtraPointRule;
};

export const SCORING_GUIDE_SECTIONS: Array<DivisionScoringInfo & { divisions: string[] }> = [
  { fieldType: 'small', touchdownPoints: 1, extraPointRule: 'none', divisions: ['Coed K-1', 'Coed 2-3', 'Girls K-2'] },
  { fieldType: 'medium', touchdownPoints: 6, extraPointRule: 'optional_1_or_2', divisions: ['Coed 4-5', 'Girls 3-5'] },
  { fieldType: 'large', touchdownPoints: 6, extraPointRule: 'optional_1_or_2', divisions: ['Coed 6-7', 'Coed 8', 'Girls 6-8'] },
];

const scoringByDivision = new Map(
  SCORING_GUIDE_SECTIONS.flatMap(section => section.divisions.map(name => [name, {
    fieldType: section.fieldType,
    touchdownPoints: section.touchdownPoints,
    extraPointRule: section.extraPointRule,
  }] as const)),
);

export function getDivisionScoringInfo(divisionGroup?: string, divisionName?: string, configuredFieldType?: string | null): DivisionScoringInfo | undefined {
  const configured = configuredFieldType?.trim().toLowerCase();
  const canonical = scoringByDivision.get(`${divisionGroup || ''} ${divisionName || ''}`.trim());
  if (canonical) return canonical;
  if (configured === 'small' || configured === 'medium' || configured === 'large') {
    return { fieldType: configured, touchdownPoints: configured === 'small' ? 1 : 6, extraPointRule: configured === 'small' ? 'none' : 'optional_1_or_2' };
  }
  return undefined;
}

export const fieldTypeLabel = (fieldType: FieldType) => `${fieldType.charAt(0).toUpperCase()}${fieldType.slice(1)} Field`;

