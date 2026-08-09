import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const publicSchedule = readFileSync(new URL('../src/app/schedule/page.tsx', import.meta.url), 'utf8');
const scoreManagement = readFileSync(new URL('../src/app/(dashboard)/admin/scores/page.tsx', import.meta.url), 'utf8');
const manualSchedule = readFileSync(new URL('../src/app/(dashboard)/admin/manual-schedule-builder/page.tsx', import.meta.url), 'utf8');

const table = publicSchedule.match(/<table[\s\S]*?<\/table>/)?.[0];
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
assert.equal(publicSchedule.match(/<table\b/g)?.length, 1, 'print and screen must share one public table');

// Longer values receive explicit additional width without leaving space for removed columns.
assert.equal(table.match(/<col className=/g)?.length, 8);
assert.equal(table.match(/w-\[17%\]/g)?.length, 2);
assert.match(table, /min-w-\[720px\]/);

// The change is public-only: administrative schedule and score tools retain useful fields.
assert.match(scoreManagement, /Home Score/);
assert.match(scoreManagement, /Away Score/);
assert.match(scoreManagement, /Score Status/);
assert.match(manualSchedule, /'Notes'/);
