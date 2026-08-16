import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const adminPage = readFileSync(new URL('../src/app/(dashboard)/admin/standings/page.tsx', import.meta.url), 'utf8');
const publicPage = readFileSync(new URL('../src/app/standings/page.tsx', import.meta.url), 'utf8');
const publicResults = readFileSync(new URL('../src/components/public/PublicResults.tsx', import.meta.url), 'utf8');
const table = readFileSync(new URL('../src/components/StandingsTable.tsx', import.meta.url), 'utf8');

// Tailwind's default xl breakpoint is 1280px: a 1920px viewport gets two cards,
// while 1024px and 390px viewports retain the base single-column grid.
for (const grid of [adminPage, publicResults]) {
  assert.match(grid, /grid items-start gap-5 xl:grid-cols-2/, 'standings use a responsive two-column desktop grid');
  assert.match(grid, /max-w-\[760px\]/, 'each division card remains compact at desktop widths');
  assert.doesNotMatch(grid, /sm:grid-cols-2|md:grid-cols-2|lg:grid-cols-2/, 'tablet widths are not forced into two columns');
}

for (const page of [adminPage, publicPage]) {
  assert.match(page, /mx-auto w-full max-w-\[1500px\]/, 'page content is centered and bounded');
}

assert.match(table, /<col className='w-12'/, 'rank is constrained to 48px');
assert.equal((table.match(/<col className='w-10 sm:w-11'/g) || []).length, 2, 'W and L are constrained to 40–44px');
assert.match(table, /table-fixed/, 'fixed table layout keeps the four columns visually grouped');
assert.match(table, /whitespace-normal break-words/, 'team names can wrap at 390px');
assert.doesNotMatch(table, /overflow-x-auto|min-w-\[/, '390px layout does not introduce horizontal scrolling');
assert.match(table, /px-2 py-2/, 'rows use compact, readable spacing');

console.log('standings responsive layout checks passed');
