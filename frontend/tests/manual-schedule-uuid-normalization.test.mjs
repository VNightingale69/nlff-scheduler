import assert from 'node:assert/strict';
import { normalizeOptionalUuid, optionalUuidChanged } from '../src/lib/manualSchedulePayload.mjs';

const uuid = '11111111-1111-4111-8111-111111111111';

assert.equal(normalizeOptionalUuid(uuid), uuid, 'a valid UUID is preserved');
assert.equal(normalizeOptionalUuid(undefined), null, 'an omitted optional UUID remains absent');
assert.equal(normalizeOptionalUuid(null), null, 'a null optional UUID remains null');
assert.equal(normalizeOptionalUuid(''), null, 'an empty select value becomes null');
assert.equal(normalizeOptionalUuid('   '), null, 'a whitespace-only select value becomes null');
assert.equal(optionalUuidChanged('', null), false, 'null to empty string is not a dirty change');
assert.equal(optionalUuidChanged(uuid, null), true, 'a selected override UUID is dirty and preserved');

console.log('manual schedule UUID normalization checks passed');
