import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/schedule-readiness/page.tsx', import.meta.url), 'utf8');

assert.match(source, /if \(!data \|\| !Array\.isArray\(data\.rows\) \|\| !data\.totals\)/,
  'successful responses must be schema-checked before rendering');
assert.match(source, /Schedule Readiness data could not be loaded\. Existing scheduling data has not been changed\./);
assert.match(source, /Administrator diagnostics/);
assert.match(source, /HTTP status/);
assert.match(source, /\{!error && loaded \? <>/,
  'empty-data sections must not render after an API failure');

console.log('schedule readiness success/error rendering checks passed');
