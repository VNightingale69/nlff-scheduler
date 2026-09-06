import assert from 'node:assert/strict';
import fs from 'node:fs';

const page = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-management/page.tsx', import.meta.url), 'utf8');
const helper = fs.readFileSync(new URL('../src/lib/scheduledGameLabel.ts', import.meta.url), 'utf8');

assert.match(page, /getScheduledGameLabel\(currentIssue\)/, 'validation rows use a human-readable game label');
assert.doesNotMatch(page, />\{currentIssue\.scheduled_game_id \|\| 'Current game'\}</, 'UUID and Current game are not rendered as the label');
assert.match(page, /title=\{currentIssue\.scheduled_game_id/, 'UUID remains available as technical tooltip context');
assert.match(page, /key=\{currentIssue\.scheduled_game_id/, 'UUID remains available for row identity');
assert.match(helper, /`\$\{home\} vs \$\{away\}`/, 'matchups use Home Team vs Away Team');
assert.match(helper, /'Schedule-level check'/, 'diagnostics without a game use a schedule-level label');
assert.match(page, /Division \/ Required Size/, 'blocking issues expose division and required physical size');
assert.match(page, /Current Layout/, 'blocking issues expose the active physical layout');
assert.match(page, /Severity/, 'the issue table distinguishes warnings from blockers');
assert.match(page, /publish_warnings/, 'non-blocking warnings share the detailed issue table');
assert.match(page, /currentIssue\.reason \|\| currentIssue\.summary/, 'blocking issues expose the exact invalidity reason');
assert.match(page, /week_ids=\$\{id\}/, 'readiness sends selected authoritative season week IDs');
assert.match(page, /sequence !== loadSequence\.current/, 'stale full-season readiness cannot replace a selected-week response');
assert.match(page, /season_week_id === publicationWeekIds\[0\]/, 'single-week readiness labels use the authoritative season week ID');
assert.match(page, /publicationWeekIds\.length > 1 \? ` - \$\{publicationWeekIds\.length\} Weeks`/, 'multi-week readiness labels show the selected scope');

console.log('schedule management validation display checks passed');
