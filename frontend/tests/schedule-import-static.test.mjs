import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../src/app/(dashboard)/admin/schedule-import/page.tsx', import.meta.url), 'utf8');
assert.match(page, /Validate and Preview/);
assert.match(page, /Replace Existing Schedule Games/);
assert.match(page, /Cancel Import/);
assert.match(page, /blocking_errors>0/);
assert.match(page, /\.csv,\.xlsx/);
console.log('schedule import staged confirmation UI checks passed');
