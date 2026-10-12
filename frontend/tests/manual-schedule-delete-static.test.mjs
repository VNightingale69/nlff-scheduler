import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/manual-schedule-builder/page.tsx', import.meta.url), 'utf8');

assert.match(source, />Delete Game<\/button>/, 'authorized actions include Delete Game');
assert.match(source, /disabled=\{deleteLoading \|\| bulkSaveLoading\}/, 'delete is disabled only while a mutation is in progress');
assert.doesNotMatch(source, /isPublishedGame|Published games cannot be deleted/, 'publication does not disable authorized deletion');
assert.match(source, /Delete Scheduled Game\?/, 'delete requires a dedicated confirmation dialog');
assert.match(source, /home_team_name.* vs .*away_team_name/, 'confirmation identifies the matchup');
assert.match(source, /method: 'DELETE'/, 'confirmation invokes the individual delete endpoint');
assert.match(source, /delete next\[game\.id\]/, 'only the deleted game pending edit is removed');
assert.doesNotMatch(source, /performDelete[\s\S]{0,500}setScheduledGamesFilters/, 'deletion preserves filters');
assert.match(source, /setError\(extractError\(e\)\)/, 'API failures are shown');
console.log('manual schedule individual deletion checks passed');

assert.match(source, /disabled=\{deleteLoading\} onClick=\{\(\) => setDeleteGame\(null\)\}>Cancel/, 'cancel closes confirmation without submitting');
assert.match(source, /disabled=\{deleteLoading \|\| bulkSaveLoading\} onClick/, 'confirmation prevents repeat submissions');
assert.match(source, /deletedGameIds.current.has/, 'stale schedule loads exclude deleted games');
assert.match(source, /setDeleteError.*Unable to delete game/, 'failure remains visible in confirmation');
