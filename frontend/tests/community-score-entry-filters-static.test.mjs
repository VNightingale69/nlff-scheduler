import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/score-entry/page.tsx', import.meta.url), 'utf8');

assert.match(source, /aria-label='Date \/ Week'/);
assert.match(source, /<option value=''>All dates \/ weeks<\/option>/);
assert.match(source, /params\.set\('week_id', filters\.weekId\)/);
assert.match(source, /params\.set\('status', filters\.status\)/);
assert.match(source, /params\.get\('week_id'\)/);
assert.match(source, /No score-entry games found for the selected filters\./);
assert.match(source, /flex flex-wrap items-end gap-2/);

console.log('Community Score Entry date/week filter checks passed.');
