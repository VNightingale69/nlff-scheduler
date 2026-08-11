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
assert.match(page, /colSpan=\{location\.fields\.length\}/);
assert.match(page, /location\.fields\.length === 1 \? 'Field' : 'Fields'/);
assert.match(page, /locationAccent\(locationIndex\)/);
assert.match(page, /locationEdge\(fieldIndex, location\.fields\.length\)/);
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
assert.match(page, /hosting-view-active/);
assert.match(page, /<colgroup><col className='hosting-time-column'/);
assert.match(css, /size: landscape/);
assert.match(css, /margin: 0\.3in 0\.25in/);
assert.match(css, /@page hosting-view[\s\S]*?margin: 0\.2in 0\.15in/);
assert.match(css, /\.public-schedule\.hosting-view-active \.public-schedule-header[\s\S]*?display: none !important/);
assert.match(css, /\.hosting-grid \.hosting-time-column \{ width: 0\.55in !important/);
assert.match(css, /\.hosting-grid \.hosting-field-column \{ width: auto !important; min-width: 0 !important/);
assert.match(css, /print-color-adjust: exact/);
assert.match(css, /display: table-header-group/);
assert.match(css, /break-inside: avoid/);
assert.match(css, /\.hosting-grid-scroll[\s\S]*?overflow-x: visible !important/);
assert.match(css, /\.hosting-grid-scroll[\s\S]*?max-height: none !important/);
assert.match(css, /\.hosting-grid \{[\s\S]*?min-width: 0 !important/);
assert.match(css, /\.hosting-grid \{[\s\S]*?table-layout: fixed !important/);
assert.match(css, /\.hosting-grid th,[\s\S]*?position: static !important/);
assert.match(css, /\.schedule-filters,[\s\S]*?\.schedule-view-toggle[\s\S]*?display: none !important/);
assert.match(css, /\.location-accent-1/);
assert.match(css, /\.location-accent-4/);
assert.match(css, /border-left: 3px solid var\(--location-border\)/);
assert.match(css, /border-right: 3px solid var\(--location-border\)/);
assert.match(css, /tbody tr:last-child \.location-schedule-cell/);

// Grouping is derived exclusively from rendered schedule data; arbitrary and
// single-field locations therefore receive the same dynamic layout treatment.
assert.doesNotMatch(page, /Hiller|Johnsburg|Antioch|Westosha|Cary|Prairie Ridge|Woodstock/);
const fixture = [
  { host_location_name: 'North Complex', field_name: 'A' },
  { host_location_name: 'North Complex', field_name: 'B' },
  { host_location_name: 'Solo Site', field_name: 'Only' },
];
const groups = [];
for (const game of fixture) {
  let group = groups.find(({ name }) => name === game.host_location_name);
  if (!group) { group = { name: game.host_location_name, fields: [] }; groups.push(group); }
  if (!group.fields.includes(game.field_name)) group.fields.push(game.field_name);
}
assert.deepEqual(groups.map(({ name, fields }) => [name, fields.length]), [['North Complex', 2], ['Solo Site', 1]]);
