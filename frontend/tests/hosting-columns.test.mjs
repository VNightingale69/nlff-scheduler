import assert from 'node:assert/strict';
import { buildHostingCells, buildHostingColumns, hostingCellKey, hostingFieldKey } from '../src/components/schedule/hostingColumns.ts';

const field = (overrides = {}) => ({ physicalFieldId: 'field-small-1', physicalAreaId: 'football-2', physicalArea: 'Football Field 2', fieldLane: 'Small 1', fieldType: 'SMALL', ...overrides });

assert.equal(buildHostingColumns([field(), field({ layout: '1 Large + 1 Small' }), field({ layout: '3 Small' }), field()]).length, 1);
assert.deepEqual(['09:00', '10:00', '11:00', '12:00'].map((time) => `${time}:${hostingFieldKey(field())}`), ['09:00:field:field-small-1', '10:00:field:field-small-1', '11:00:field:field-small-1', '12:00:field:field-small-1']);
assert.equal(buildHostingColumns([field({ physicalFieldId: 'football-1-small-1', physicalAreaId: 'football-1', physicalArea: 'Football Field 1' }), field()]).length, 2);

const warnings = [];
const duplicates = buildHostingColumns([field(), field({ physicalFieldId: 'duplicate-id' })], (message) => warnings.push(message));
assert.equal(duplicates.length, 1);
assert.deepEqual(duplicates[0].physicalFieldIds, ['field-small-1', 'duplicate-id']);
assert.equal(warnings.length, 1);
assert.match(warnings[0], /Duplicate physical field identity detected[\s\S]*Field ID A: field-small-1[\s\S]*Field ID B: duplicate-id/);

// Formatting from different sources cannot create another identity or label.
const differentlyFormatted = buildHostingColumns([
  field({ physicalFieldId: '123', fieldLane: 'Football Field 2 / Small 1' }),
  field({ physicalFieldId: '123', fieldLane: 'Football Field 2 - Small 1' }),
]);
assert.equal(differentlyFormatted.length, 1);
assert.equal(differentlyFormatted[0].label, 'Football Field 2 - Small 1');
assert.equal(hostingFieldKey(field({ physicalFieldId: null, fieldLane: 'Football Field 2 / Small 1' })), hostingFieldKey(field({ physicalFieldId: null, fieldLane: 'Football Field 2 - Small 1' })));

assert.deepEqual(buildHostingColumns([
  field({ physicalFieldId: 'small-3', physicalArea: 'Soccer Field', physicalAreaId: 'soccer', fieldLane: 'Small 3' }),
  field({ physicalFieldId: 'large-1', fieldLane: 'Large 1', fieldType: 'LARGE' }),
  field({ physicalFieldId: 'small-1' }),
]).map((column) => `${column.area} - ${column.lane}`), ['Football Field 2 - Large 1', 'Football Field 2 - Small 1', 'Soccer Field - Small 3']);

console.log('hosting column regression checks passed');

const game = (overrides = {}) => ({ id: 'grey-gold', date: '2026-08-23', time: '12:00:00', ...field(), ...overrides });
// Legacy duplicate database IDs share one canonical column without losing games.
const duplicateIdGames = [game({ id: 'canonical-game' }), game({ id: 'duplicate-game', physicalFieldId: 'duplicate-id' })];
const repairedColumns = buildHostingColumns(duplicateIdGames, () => {});
const repairedCells = buildHostingCells(duplicateIdGames, () => {}, repairedColumns);
assert.equal(repairedColumns.length, 1);
assert.deepEqual(repairedCells.get(`2026-08-23:12:00:00:${repairedColumns[0].key}`)?.map(({ id }) => id), ['canonical-game', 'duplicate-game']);

const targeted = game({ homeTeam: 'Antioch Coed 2-3 Grey', awayTeam: 'Jbrg Coed 2-3 Gold' });
const targetedCells = buildHostingCells([targeted]);
assert.equal(hostingCellKey(targeted), '2026-08-23:12:00:00:field:field-small-1');
assert.deepEqual(targetedCells.get('2026-08-23:12:00:00:field:field-small-1'), [targeted]);
for (const wrongId of ['football-1-small-1', 'soccer-small-1', 'soccer-small-2', 'soccer-small-3']) {
  assert.equal(targetedCells.has(`2026-08-23:12:00:00:field:${wrongId}`), false);
}

// Identical short names and simultaneous, independent area layouts never merge.
const simultaneous = [
  game({ id: 'football-1-game', physicalFieldId: 'football-1-small-1', physicalAreaId: 'football-1', physicalArea: 'Football Field 1', layout: '3 Small' }),
  game({ id: 'football-2-game', physicalFieldId: 'football-2-small-1', physicalAreaId: 'football-2', physicalArea: 'Football Field 2', layout: '1 Large + 1 Small' }),
  game({ id: 'soccer-game', physicalFieldId: 'soccer-small-1', physicalAreaId: 'soccer', physicalArea: 'Soccer Field', layout: '3 Small' }),
];
const simultaneousCells = buildHostingCells(simultaneous);
assert.equal(simultaneousCells.size, 3);
for (const assigned of simultaneous) assert.deepEqual(simultaneousCells.get(hostingCellKey(assigned))?.map(({ id }) => id), [assigned.id]);

const diagnosticWarnings = [];
buildHostingCells([targeted, targeted, game({ id: 'orphan', physicalFieldId: null })], (message) => diagnosticWarnings.push(message));
assert.ok(diagnosticWarnings.some((message) => message.includes('duplicate game id: grey-gold')));
assert.ok(diagnosticWarnings.some((message) => message.includes('has no physical_field_id')));
