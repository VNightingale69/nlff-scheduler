import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../src/app/standings/page.tsx', import.meta.url), 'utf8');
const results = readFileSync(new URL('../src/components/public/PublicResults.tsx', import.meta.url), 'utf8');
const header = readFileSync(new URL('../src/components/public/PublicHeader.tsx', import.meta.url), 'utf8');

assert.match(page, /max-w-\[1500px\]/, 'public standings uses a wide, bounded container');
assert.match(header, /max-w-\[1500px\]/, 'public header aligns with the wide content');
assert.match(results, /<CommunityLogo src=\{row\.community_logo_url\}/, 'standings renders the logo included in its response');
assert.match(results, /row\.organization_name \|\| row\.community_name/, 'standings displays the API community name');
assert.match(results, /name=\{communityName\}/, 'CommunityLogo receives a name for its initials fallback');
assert.equal((results.match(/fetch\(/g) || []).length, 1, 'standings performs one request rather than one logo request per row');
assert.match(results, /\{row\.rank\}/, 'existing API ranking remains displayed');
assert.match(results, /value=\{division\} onChange=/, 'division filter remains interactive');
assert.match(results, /overflow-x-auto.*min-w-\[650px\]/s, 'standings remains usable through controlled mobile scrolling');
assert.match(results, /text-center[^>]*>W</, 'statistical columns are centered');

console.log('public standings static checks passed');
