export type DivisionLike = {
  name?: string | null;
  division_group?: string | null;
};

const divisionGroupLabelMap: Record<string, string> = {
  COED: 'Coed',
  GIRLS: 'Girls',
};

export function getDivisionLabel(division: DivisionLike | null | undefined): string {
  if (!division) return '';
  const name = (division.name || '').trim();
  const group = (division.division_group || '').trim().toUpperCase();
  const groupLabel = divisionGroupLabelMap[group];

  if (groupLabel && name) return `${groupLabel} ${name}`;
  if (name) return name;
  return groupLabel || '';
}
