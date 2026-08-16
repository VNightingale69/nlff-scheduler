import assert from 'node:assert/strict';
import fs from 'node:fs';
const read = path => fs.readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const root = read('app/page.tsx');
const header = read('components/public/PublicHeader.tsx');
const results = read('components/public/PublicResults.tsx');
for (const [label, href] of [['Schedule','/schedule'],['Standings','/standings'],['Scores','/scores'],['Rulebook','/rulebook']]) {
  assert.match(root, new RegExp(`href: '${href}', title: '${label}'`));
}
assert.match(root, /min-\[360px\]:grid-cols-2/);
assert.match(root, /lg:grid-cols-4/);
assert.match(root, /dashboardLinks\.map\(link => <PublicDashboardCard/);
const card = read('components/public/PublicDashboardCard.tsx');
for (const variant of ['green', 'blue', 'orange', 'purple']) assert.match(card, new RegExp(`${variant}:`));
assert.match(card, /focus-visible:ring-4/);
assert.match(card, /aria-label=\{`\$\{title\}: \$\{description\}`\}/);
assert.ok(!root.includes('redirect('));
assert.match(header, /href='\/login'.*>Admin Login</);
assert.ok(header.includes("['/', 'Home']"), 'public navigation includes Home');
for (const page of ['app/schedule/page.tsx','app/standings/page.tsx','app/scores/page.tsx','app/rulebook/page.tsx']) assert.match(read(page), /PublicLayout/);
for (const label of ['Field Setup','Hosting Availability','Score Entry','User Administration']) assert.ok(!header.includes(label));
assert.match(results, /\/public\/standings/);
assert.match(results, /filter\(game => game\.is_official/);
console.log('public dashboard static checks passed');
