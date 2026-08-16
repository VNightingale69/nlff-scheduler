import { formatPhysicalFieldLabel, normalizeFieldIdentity, physicalFieldLabelParts } from '../../lib/physicalField.ts';

export type HostingField = {
  physicalFieldId?: string | null;
  physicalAreaId?: string | null;
  physicalArea: string;
  fieldLane: string;
  fieldType?: string | null;
  active?: boolean | null;
  deletedAt?: string | null;
  source?: string | null;
};

export type HostingColumn = {
  key: string;
  physicalFieldId?: string | null;
  physicalAreaId?: string | null;
  area: string;
  lane: string;
  fieldType?: string | null;
  label: string;
  /** Every database identity folded into this canonical logical column. */
  physicalFieldIds: string[];
};

export type HostingPlacement = HostingField & {
  id?: string;
  date: string;
  time: string;
};

/** A physical field is a column; dated slots and layout memberships are not. */
export const hostingFieldKey = (field: HostingField) => field.physicalFieldId
  ? `field:${field.physicalFieldId}`
  : `legacy:${field.physicalAreaId || 'area'}:${normalizeFieldIdentity(field.physicalArea, field.fieldLane)}`;

/** The saved physical field assignment is the complete identity of a hosting cell. */
export const hostingCellKey = (game: HostingPlacement) => `${game.date}:${game.time}:${hostingFieldKey(game)}`;

export function buildHostingCells<T extends HostingPlacement>(games: T[], warn: (message: string) => void = console.warn, columns?: HostingColumn[]): Map<string, T[]> {
  const cells = new Map<string, T[]>();
  const canonicalKeyById = new Map(columns?.flatMap((column) => column.physicalFieldIds.map((id) => [id, column.key] as const)) || []);
  const seenIds = new Set<string>();
  for (const game of games) {
    const fieldKey = game.physicalFieldId ? canonicalKeyById.get(game.physicalFieldId) : undefined;
    const cellKey = `${game.date}:${game.time}:${fieldKey || hostingFieldKey(game)}`;
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
  const columnsByLogicalIdentity = new Map<string, HostingColumn>();
  for (const field of fields) {
    const parts = physicalFieldLabelParts({ physicalAreaName: field.physicalArea, fieldName: field.fieldLane });
    const label = formatPhysicalFieldLabel(parts.physicalAreaName, parts.fieldName);
    const logicalKey = `${field.physicalAreaId || normalizeFieldIdentity(parts.physicalAreaName, '')}:${normalizeFieldIdentity('', parts.fieldName)}`;
    const existingLogical = columnsByLogicalIdentity.get(logicalKey);
    if (existingLogical) {
      if (field.physicalFieldId && !existingLogical.physicalFieldIds.includes(field.physicalFieldId)) {
        warn(`Duplicate physical field identity detected\n\nPhysical Area: ${parts.physicalAreaName}\nField: ${parts.fieldName}\nField ID A: ${existingLogical.physicalFieldId}\nField ID B: ${field.physicalFieldId}\nPhysical Area ID: ${field.physicalAreaId || 'unknown'}\n\nBoth IDs were folded into canonical column ${existingLogical.key}.`);
        existingLogical.physicalFieldIds.push(field.physicalFieldId);
      }
      continue;
    }
    const columnKey = hostingFieldKey(field);
    const column = { key: columnKey, physicalFieldId: field.physicalFieldId, physicalAreaId: field.physicalAreaId, area: parts.physicalAreaName, lane: parts.fieldName, label, fieldType: field.fieldType, physicalFieldIds: field.physicalFieldId ? [field.physicalFieldId] : [] };
    columnsByField.set(columnKey, column);
    columnsByLogicalIdentity.set(logicalKey, column);
  }
  return Array.from(columnsByField.values()).sort((a, b) => naturalCompare(a.area, b.area) || naturalCompare(a.fieldType || '', b.fieldType || '') || naturalCompare(a.lane, b.lane) || naturalCompare(a.key, b.key));
}
