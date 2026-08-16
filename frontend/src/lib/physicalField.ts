export type PhysicalFieldLabelParts = { physicalAreaName?: string | null; fieldName?: string | null };

const clean = (value?: string | null) => (value || '').trim();

/** Normalize old combined labels without changing the persisted names. */
export function physicalFieldLabelParts({ physicalAreaName, fieldName }: PhysicalFieldLabelParts) {
  const area = clean(physicalAreaName);
  let field = clean(fieldName);
  if (area && field.toLocaleLowerCase().startsWith(area.toLocaleLowerCase())) {
    field = field.slice(area.length).replace(/^\s*(?:\/|\s-\s)\s*/, '').trim();
  }
  if (!area) {
    const match = field.match(/^(.+?)\s+(?:\/|-)\s+(.+)$/);
    if (match) return { physicalAreaName: match[1].trim(), fieldName: match[2].trim() };
  }
  return { physicalAreaName: area, fieldName: field };
}

/** The shared display formatter for a physical area and configurable field. */
export function formatPhysicalFieldLabel(physicalAreaName?: string | null, fieldName?: string | null) {
  const parts = physicalFieldLabelParts({ physicalAreaName, fieldName });
  return [parts.physicalAreaName, parts.fieldName].filter(Boolean).join(' - ') || 'Field Unassigned';
}

/** Compatibility identity only for historical rows lacking physical_field_id. */
export function normalizeFieldIdentity(physicalAreaName?: string | null, fieldName?: string | null) {
  const parts = physicalFieldLabelParts({ physicalAreaName, fieldName });
  const normalize = (value: string) => value.trim().toLocaleLowerCase().replace(/[\s/_-]+/g, ' ');
  return `${normalize(parts.physicalAreaName)}::${normalize(parts.fieldName)}`;
}
