import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../src/app/standings/page.tsx', import.meta.url), 'utf8');
const results = readFileSync(new URL('../src/components/public/PublicResults.tsx', import.meta.url), 'utf8');
const table = readFileSync(new URL('../src/components/StandingsTable.tsx', import.meta.url), 'utf8');

assert.match(page, /max-w-\[1500px\]/, 'public standings uses a centered bounded page container');
assert.match(results, /<StandingsTable rows=\{block\.standings\}/, 'public standings uses the shared table');
assert.match(table, /<CommunityLogo src=\{row\.community_logo_url\}/, 'standings renders the logo included in its response');
assert.match(table, /row\.organization_name \|\| row\.community_name/, 'standings provides the API community name to the logo fallback');
assert.match(table, /name=\{communityName\}/, 'CommunityLogo receives a name for its initials fallback');
assert.equal((results.match(/fetch\(/g) || []).length, 1, 'standings performs one request rather than one logo request per row');
assert.match(table, /\{row\.rank\}/, 'existing API ranking remains displayed');
assert.match(results, /value=\{division\} onChange=/, 'division filter remains interactive');
assert.doesNotMatch(table, /overflow-x-auto|min-w-\[/, 'standings does not require horizontal scrolling on mobile');
assert.match(table, /text-center[^>]*>W</, 'statistical columns are centered');
assert.deepEqual([...table.matchAll(/<th[^>]*>([^<]+)<\/th>/g)].map(match => match[1]), ['Rank', 'Team', 'W', 'L']);
for (const removed of ['Community', 'Division', 'T', 'GP', 'Scheduled', 'Remaining']) assert.doesNotMatch(table, new RegExp(`>${removed}<`));

console.log('public standings static checks passed');
