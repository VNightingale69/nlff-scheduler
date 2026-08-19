import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/manual-schedule-builder/page.tsx', import.meta.url), 'utf8');

assert.match(source, />Delete Game<\/button>/, 'authorized actions include Delete Game');
assert.match(source, /disabled=\{isPublishedGame\(g\)\}/, 'published games have a disabled delete action');
assert.match(source, /Published games cannot be deleted from the Manual Schedule Builder\./, 'published protection is explained');
assert.match(source, /Delete Scheduled Game\?/, 'delete requires a dedicated confirmation dialog');
assert.match(source, /home_team_name.* vs .*away_team_name/, 'confirmation identifies the matchup');
assert.match(source, /method: 'DELETE'/, 'confirmation invokes the individual delete endpoint');
assert.match(source, /delete next\[game\.id\]/, 'only the deleted game pending edit is removed');
assert.doesNotMatch(source, /performDelete[\s\S]{0,500}setScheduledGamesFilters/, 'deletion preserves filters');
assert.match(source, /setError\(extractError\(e\)\)/, 'API failures are shown');
console.log('manual schedule individual deletion checks passed');
