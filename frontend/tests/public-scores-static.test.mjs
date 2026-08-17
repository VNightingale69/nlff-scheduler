import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const results = readFileSync(new URL('../src/components/public/PublicResults.tsx', import.meta.url), 'utf8');
const teamWithLogo = readFileSync(new URL('../src/components/TeamWithLogo.tsx', import.meta.url), 'utf8');

for (const side of ['home', 'away']) {
  assert.match(results, new RegExp(`teamName=\\{game\\.${side}_team\\}`));
  assert.match(results, new RegExp(`logoUrl=\\{game\\.${side}_organization_logo_url\\}`));
  assert.match(results, new RegExp(`organizationName=\\{game\\.${side}_organization_name\\}`));
}

assert.match(results, /Home Team.*Home Score.*Away Team.*Away Score/);
assert.match(results, /md:hidden/);
assert.match(results, /grid-cols-\[minmax\(0,1fr\)_auto\]/);
assert.match(results, /logoSize=\{32\}/);
assert.match(teamWithLogo, /<CommunityLogo/);
assert.match(teamWithLogo, /gap-2/);
assert.match(teamWithLogo, /organizationName \|\| teamName/);
assert.match(teamWithLogo, /<span className='min-w-0 break-words'>\{teamName\}<\/span>/);

console.log('public scores logo tests passed');
