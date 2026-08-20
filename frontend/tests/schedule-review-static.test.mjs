import assert from 'node:assert/strict';
import fs from 'node:fs';

const page = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-review/page.tsx', import.meta.url), 'utf8');
const shell = fs.readFileSync(new URL('../src/components/DashboardShell.tsx', import.meta.url), 'utf8');

assert.match(shell, /'schedule-review'/, 'Community navigation should expose Schedule Review');
assert.match(page, /Read Only/);
assert.match(page, /Draft games, times, fields, and matchups may change/);
assert.match(page, /useState\('league'\)/, 'Schedule review defaults to the entire league');
assert.match(page, /organization_id.*Communities/, 'Community is an optional display filter');
assert.doesNotMatch(page, /setScope/, 'Users cannot accidentally default back to an organization-scoped view');
assert.match(page, /By Date/);
assert.match(page, /By Host Location/);
assert.match(page, /By Team/);
assert.match(page, /By Division/);
assert.match(page, /Hosting View/);
assert.match(page, /PREPUBLISHED SCHEDULE — SUBJECT TO CHANGE/);
assert.match(page, /some\(\(week\) => !week\.is_published\)/, 'Only truly draft weeks trigger the draft notice');
assert.match(page, /week\.is_published && week\.has_pending_changes/, 'Warning consumes the canonical backend state');
assert.match(page, /The current administrative schedule contains changes that have not yet been published\./);
assert.doesNotMatch(page, /Official public version differs/);
for (const forbidden of ['Publish Week', 'Unpublish', 'Manual Override', 'Regenerate']) assert.doesNotMatch(page, new RegExp(forbidden));

console.log('schedule review static checks passed');
