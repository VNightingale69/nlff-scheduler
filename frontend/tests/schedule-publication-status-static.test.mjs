import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/app/(dashboard)/admin/schedule-management/page.tsx', import.meta.url), 'utf8');
assert.match(source, /bg-amber-100 text-amber-800/);
assert.match(source, /working schedule contains changes that have not yet been republished/);
assert.match(source, /working schedule matches the currently published schedule/);
assert.match(source, /week\.publication_status === 'PUBLISHED_CHANGES_PENDING'/);
