import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const publicSchedule = readFileSync(new URL('../src/app/schedule/page.tsx', import.meta.url), 'utf8');
const globalStyles = readFileSync(new URL('../src/app/globals.css', import.meta.url), 'utf8');
const scoreManagement = readFileSync(new URL('../src/app/(dashboard)/admin/scores/page.tsx', import.meta.url), 'utf8');
const manualSchedule = readFileSync(new URL('../src/app/(dashboard)/admin/manual-schedule-builder/page.tsx', import.meta.url), 'utf8');

const table = publicSchedule.match(/<table data-view='list'[\s\S]*?<\/table>/)?.[0];
assert.ok(table, 'the public schedule table must render');

for (const heading of ['Date', 'Time', 'Host Location', 'Field', 'Division', 'Home Team', 'Away Team', 'Game Type']) {
  assert.match(table, new RegExp(`>${heading}<`), `${heading} must remain in the public schedule`);
}

for (const removedHeading of ['Game Status', 'Notes', 'Coach Contacts', 'Score']) {
  assert.doesNotMatch(table, new RegExp(`>${removedHeading}<`, 'i'), `${removedHeading} must not render in the public schedule`);
}

for (const removedCell of ['game_status_label', 'public_notes', 'coach_contacts_visible', 'home_team_coach_name', 'public_score_status', 'home_score', 'away_score']) {
  assert.doesNotMatch(table, new RegExp(`g\\.${removedCell}\\b`), `${removedCell} must not have a public row or responsive representation`);
}

// Print/PDF invokes the browser print dialog over this same, simplified table.
assert.match(publicSchedule, /onClick=\{\(\) => window\.print\(\)\}>Print \/ PDF/);
assert.match(publicSchedule, /view === 'list'/, 'the existing list is rendered only in List View');

// The public page uses the available desktop width while preserving tablet overflow.
assert.match(publicSchedule, /w-\[96%\] max-w-\[1800px\]/);
assert.match(table, /w-full min-w-\[1180px\]/);
assert.doesNotMatch(table, /text-xs/);
assert.match(table, /text-\[15px\]/);

// Headers, data, and each team logo/name unit remain centered on screen.
assert.match(table, /<thead className='[^']*text-center/);
assert.match(globalStyles, /\.public-schedule \.schedule-table th,\s*\.public-schedule \.schedule-table td\s*{\s*text-align: center;\s*vertical-align: middle;/);
assert.equal(table.match(/team-content flex items-center justify-center gap-2 text-center/g)?.length, 2);

// Team names receive the largest share without leaving space for removed columns.
assert.equal(table.match(/<col className=/g)?.length, 8);
assert.equal(table.match(/w-\[19%\]/g)?.length, 2);

// Printing removes the desktop width constraints and assigns extra room to fields and teams.
assert.match(publicSchedule, /schedule-table-wrapper overflow-x-auto/);
assert.match(table, /schedule-table w-full min-w-\[1180px\]/);
assert.match(globalStyles, /@page\s*{\s*size: landscape;\s*margin: 0\.3in 0\.25in;/);
assert.match(globalStyles, /\.public-schedule,\s*\.public-schedule-header,\s*\.schedule-table-wrapper\s*{[\s\S]*?width: 100% !important;[\s\S]*?max-width: none !important;/);
assert.match(globalStyles, /\.schedule-table\s*{[\s\S]*?width: 100% !important;[\s\S]*?min-width: 0 !important;[\s\S]*?table-layout: auto !important;/);
assert.match(globalStyles, /\.schedule-table col:nth-child\(4\)\s*{ width: 18% !important; }/);
assert.match(globalStyles, /\.schedule-table col:nth-child\(6\),\s*\.schedule-table col:nth-child\(7\)\s*{ width: 18% !important; }/);
assert.match(globalStyles, /\.schedule-table thead\s*{\s*display: table-header-group;/);
assert.match(globalStyles, /\.schedule-table tr\s*{[\s\S]*?break-inside: avoid;[\s\S]*?page-break-inside: avoid;/);
assert.match(globalStyles, /\.schedule-table th,\s*\.schedule-table td\s*{[\s\S]*?text-align: center !important;[\s\S]*?vertical-align: middle !important;/);
assert.match(globalStyles, /\.schedule-table \.team-content\s*{[\s\S]*?align-items: center !important;[\s\S]*?justify-content: center !important;[\s\S]*?text-align: center !important;/);

// The change is public-only: administrative schedule and score tools retain useful fields.
assert.match(scoreManagement, /Home Score/);
assert.match(scoreManagement, /Away Score/);
assert.match(scoreManagement, /Score Status/);
assert.match(manualSchedule, /'Notes'/);
