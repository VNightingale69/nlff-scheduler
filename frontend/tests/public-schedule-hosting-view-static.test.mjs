import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../src/app/schedule/page.tsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/app/globals.css', import.meta.url), 'utf8');

assert.match(page, /\['list', 'List View'\], \['hosting', 'Hosting View'\]/);
assert.match(page, /searchParams\.get\('view'\) === 'hosting'/);
assert.match(page, /query\.set\('view', 'hosting'\)/);
assert.match(page, /function HostingSchedule/);
assert.match(page, /rowSpan=\{2\}[\s\S]*?>Time</);
assert.match(page, /scope='colgroup'/);
assert.match(page, /scope='row'/);
assert.match(page, /aria-label='No game'>—/);
assert.match(page, /game\.turf_field_slot \|\|/);
assert.match(page, /game\.field_type \|\| assignedName/);
assert.match(page, /home_team_logo_url/);
assert.match(page, /away_team_logo_url/);
assert.match(page, /overflow-x-auto/);
assert.match(page, /sticky left-0/);
assert.match(page, /sticky top-0/);
assert.match(page, /max-w-\[1800px\]/);
assert.match(css, /size: landscape/);
assert.match(css, /display: table-header-group/);
assert.match(css, /break-inside: avoid/);
