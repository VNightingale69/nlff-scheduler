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
assert.match(page, /currentIssue\.reason \|\| currentIssue\.summary/, 'blocking issues expose the exact invalidity reason');

console.log('schedule management validation display checks passed');
