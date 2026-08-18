import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const results = readFileSync(new URL('../src/components/public/PublicResults.tsx', import.meta.url), 'utf8');
const teamWithLogo = readFileSync(new URL('../src/components/TeamWithLogo.tsx', import.meta.url), 'utf8');

for (const side of ['home', 'away']) {
  assert.match(results, new RegExp(`teamName=\\{game\\.${side}_team\\}`));
  assert.match(results, new RegExp(`logoUrl=\\{game\\.${side}_organization_logo_url\\}`));
  assert.match(results, new RegExp(`organizationName=\\{game\\.${side}_organization_name\\}`));
}

assert.match(results, /Home.*Away/s);
assert.match(results, /grid-cols-\[minmax\(0,1fr\)_auto\]/);
assert.match(results, /logoSize=\{36\}/);
assert.match(results, /host_location/);
assert.match(results, /fieldTypeLabel/);
assert.match(teamWithLogo, /<CommunityLogo/);
assert.match(teamWithLogo, /gap-2/);
assert.match(teamWithLogo, /organizationName \|\| teamName/);
assert.match(teamWithLogo, /<span className='min-w-0 break-words'>\{teamName\}<\/span>/);
assert.match(results, /All Communities/);
assert.match(results, /All Dates/);
assert.match(results, /All Divisions/);
assert.match(results, /No published scores match these filters\./);
assert.match(results, /onClick=\{clearFilters\}/);
assert.match(results, /window\.history\.replaceState/);

console.log('public scores logo tests passed');
