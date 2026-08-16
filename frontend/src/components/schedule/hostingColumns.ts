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

export type HostingPlacement = HostingField & {
  id?: string;
  date: string;
  time: string;
};

/** A physical field is a column; dated slots and layout memberships are not. */
export const hostingFieldKey = (field: HostingField) => field.physicalFieldId
  ? `field:${field.physicalFieldId}`
  : `unassigned:${field.physicalAreaId || field.physicalArea}:${field.fieldLane}`;

/** The saved physical field assignment is the complete identity of a hosting cell. */
export const hostingCellKey = (game: HostingPlacement) => `${game.date}:${game.time}:${hostingFieldKey(game)}`;

export function buildHostingCells<T extends HostingPlacement>(games: T[], warn: (message: string) => void = console.warn): Map<string, T[]> {
  const cells = new Map<string, T[]>();
  const seenIds = new Set<string>();
  for (const game of games) {
    const cellKey = hostingCellKey(game);
    const contents = cells.get(cellKey) || [];
    contents.push(game);
    cells.set(cellKey, contents);
    if (!game.physicalFieldId) warn(`Hosting View game ${game.id || '(unknown id)'} has no physical_field_id; its saved field assignment cannot be verified.`);
    if (game.id && seenIds.has(game.id)) warn(`Hosting View duplicate game id: ${game.id}`);
    if (game.id) seenIds.add(game.id);
  }
  const renderedIds = new Set(Array.from(cells.values()).flat().map((game) => game.id).filter(Boolean));
  const expectedIds = new Set(games.map((game) => game.id).filter(Boolean));
  const missingIds = Array.from(expectedIds).filter((id) => !renderedIds.has(id));
  const renderedCount = Array.from(cells.values()).reduce((count, cell) => count + cell.length, 0);
  if (renderedCount !== games.length || missingIds.length) warn(`Hosting View rendering mismatch. Expected games: ${games.length}; rendered games: ${renderedCount}; missing game IDs: ${missingIds.join(', ') || 'none'}`);
  return cells;
}

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
