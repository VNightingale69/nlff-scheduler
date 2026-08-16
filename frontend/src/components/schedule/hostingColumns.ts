export type HostingField = {
  physicalFieldId?: string | null;
  physicalAreaId?: string | null;
  physicalArea: string;
  fieldLane: string;
  fieldType?: string | null;
};

export type HostingColumn = {
  key: string;
  physicalFieldId?: string | null;
  physicalAreaId?: string | null;
  area: string;
  lane: string;
  fieldType?: string | null;
};

/** A physical field is a column; dated slots and layout memberships are not. */
export const hostingFieldKey = (field: HostingField) => field.physicalFieldId
  ? `field:${field.physicalFieldId}`
  : `unassigned:${field.physicalAreaId || field.physicalArea}:${field.fieldLane}`;

const naturalCompare = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' }).compare;

export function buildHostingColumns(fields: HostingField[], warn: (message: string) => void = console.warn): HostingColumn[] {
  const columnsByField = new Map<string, HostingColumn>();
  const idsByAreaAndLabel = new Map<string, string>();
  for (const field of fields) {
    const columnKey = hostingFieldKey(field);
    if (!columnsByField.has(columnKey)) columnsByField.set(columnKey, { key: columnKey, physicalFieldId: field.physicalFieldId, physicalAreaId: field.physicalAreaId, area: field.physicalArea, lane: field.fieldLane, fieldType: field.fieldType });
    if (field.physicalFieldId) {
      const labelKey = `${field.physicalAreaId || field.physicalArea}:${field.physicalArea} - ${field.fieldLane}`;
      const previousId = idsByAreaAndLabel.get(labelKey);
      if (previousId && previousId !== field.physicalFieldId) warn(`Duplicate field display label detected:\n${field.physicalArea} - ${field.fieldLane}\n\nfield_id A: ${previousId}\nfield_id B: ${field.physicalFieldId}\nphysical_area_id: ${field.physicalAreaId || 'unknown'}`);
      else idsByAreaAndLabel.set(labelKey, field.physicalFieldId);
    }
  }
  return Array.from(columnsByField.values()).sort((a, b) => naturalCompare(a.area, b.area) || naturalCompare(a.fieldType || '', b.fieldType || '') || naturalCompare(a.lane, b.lane) || naturalCompare(a.key, b.key));
}
