import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/scores/page.tsx', import.meta.url), 'utf8');

for (const label of ['Division', 'Community', 'Host Location']) assert.match(source, new RegExp(`<select aria-label='${label}'`));
for (const placeholder of ['Division ID', 'Community ID', 'Host Location ID']) assert.doesNotMatch(source, new RegExp(`placeholder='${placeholder}'`));
assert.match(source, /<option value=''>All Divisions<\/option>/);
assert.match(source, /<option value=''>All Communities<\/option>/);
assert.match(source, /<option value=''>All Host Locations<\/option>/);
assert.match(source, /host\.organization_id === filters\.organization_id/);
assert.match(source, /host_location_id: !organization_id[\s\S]*\? current\.host_location_id : ''/);
assert.match(source, /Promise\.allSettled/);

console.log('Score Management reference filter checks passed.');
