import assert from 'node:assert/strict';
import { buildHostingColumns, hostingFieldKey } from '../src/components/schedule/hostingColumns.ts';

const field = (overrides = {}) => ({ physicalFieldId: 'field-small-1', physicalAreaId: 'football-2', physicalArea: 'Football Field 2', fieldLane: 'Small 1', fieldType: 'SMALL', ...overrides });

assert.equal(buildHostingColumns([field(), field({ layout: '1 Large + 1 Small' }), field({ layout: '3 Small' }), field()]).length, 1);
assert.deepEqual(['09:00', '10:00', '11:00', '12:00'].map((time) => `${time}:${hostingFieldKey(field())}`), ['09:00:field:field-small-1', '10:00:field:field-small-1', '11:00:field:field-small-1', '12:00:field:field-small-1']);
assert.equal(buildHostingColumns([field({ physicalFieldId: 'football-1-small-1', physicalAreaId: 'football-1', physicalArea: 'Football Field 1' }), field()]).length, 2);

const warnings = [];
const duplicates = buildHostingColumns([field(), field({ physicalFieldId: 'duplicate-id' })], (message) => warnings.push(message));
assert.equal(duplicates.length, 2);
assert.equal(warnings.length, 1);
assert.match(warnings[0], /field_id A: field-small-1[\s\S]*field_id B: duplicate-id[\s\S]*physical_area_id: football-2/);

assert.deepEqual(buildHostingColumns([
  field({ physicalFieldId: 'small-3', physicalArea: 'Soccer Field', physicalAreaId: 'soccer', fieldLane: 'Small 3' }),
  field({ physicalFieldId: 'large-1', fieldLane: 'Large 1', fieldType: 'LARGE' }),
  field({ physicalFieldId: 'small-1' }),
]).map((column) => `${column.area} - ${column.lane}`), ['Football Field 2 - Large 1', 'Football Field 2 - Small 1', 'Soccer Field - Small 3']);

console.log('hosting column regression checks passed');
