import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-readiness/page.tsx', import.meta.url), 'utf8');

assert.match(source, /if \(!data \|\| !Array\.isArray\(data\.rows\) \|\| !data\.totals\)/,
  'successful responses must be schema-checked before rendering');
assert.match(source, /Schedule Readiness data could not be loaded\. Existing scheduling data has not been changed\./);
assert.match(source, /Administrator diagnostics/);
assert.match(source, /apiFetch\('\/schedule-readiness', \{\}, token\)/,
  'Schedule Readiness uses the shared bearer-token API client');
assert.match(source, /\}, \[token\]\);/,
  'the request waits for and reacts to the authenticated session token');
assert.match(source, /if \(status === 401\) return 'Your login session is not being accepted by the scheduling API\./);
assert.match(source, /if \(status === 403\) return 'You are signed in but do not have permission to access Schedule Readiness\.'/);
assert.match(source, /if \(status === 404\) return 'Schedule Readiness API endpoint was not found\.'/);
assert.match(source, /if \(status >= 500\) return 'The server encountered an error while loading Schedule Readiness\.'/);
assert.match(source, /if \(status === 0\) return 'Unable to connect to server'/,
  'only a request without an HTTP response is classified as a network failure');
assert.match(source, /if \(status === 401\) return 'Authentication required'/);
assert.match(source, /<dt>Endpoint<\/dt><dd>\/api\/schedule-readiness<\/dd>/);
assert.doesNotMatch(source, /setError\(e\?\.message/,
  'raw authentication responses cannot be mislabeled by page-specific handling');
assert.match(source, /\{!error && loaded \? <>/,
  'empty-data sections must not render after an API failure');
assert.match(source, /Generated game-slot capacity/, 'planning capacity is explicitly distinguished from physical capacity');
assert.match(source, /Saved schedule assignments:/, 'host plan reports authoritative saved-assignment readiness separately');

console.log('schedule readiness success/error rendering checks passed');
