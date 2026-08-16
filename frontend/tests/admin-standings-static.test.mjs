import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../src/app/(dashboard)/admin/standings/page.tsx', import.meta.url), 'utf8');
const table = readFileSync(new URL('../src/components/StandingsTable.tsx', import.meta.url), 'utf8');

assert.match(page, /<StandingsTable rows=\{division\.standings\} divisionId=\{division\.division\.id\}/);
assert.match(page, /division\.division\.division_group.*division\.division\.name/, 'configured division grouping remains visible');
assert.match(page, /Create Tournament from Standings/, 'authorized tournament action remains available');
assert.deepEqual([...table.matchAll(/<th[^>]*>([^<]+)<\/th>/g)].map(match => match[1]), ['Rank', 'Team', 'W', 'L']);
for (const diagnostic of ['Official/Played', 'Missing:', 'Pending:', 'Flagged/Conflict', 'Future:', 'Calculated at:', 'Standings may be incomplete']) {
  assert.doesNotMatch(page, new RegExp(diagnostic), `${diagnostic} is not permanently displayed`);
}
assert.match(table, /size=\{28\}/, 'team logos remain mobile-friendly');
assert.match(table, /whitespace-normal break-words/, 'team names may wrap rather than truncate');
assert.doesNotMatch(table, /overflow-x-auto|min-w-\[/, 'shared standings fit mobile without horizontal scrolling');

console.log('admin standings static checks passed');
