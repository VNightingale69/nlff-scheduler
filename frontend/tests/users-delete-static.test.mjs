import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/users/page.tsx', import.meta.url), 'utf8');
assert.match(source, /Delete Community Administrator/);
assert.match(source, /associated community, teams, facilities, schedules, and league data will not be deleted/);
assert.match(source, /method: 'DELETE'/);
assert.match(source, /User deleted successfully/);
assert.match(source, /await load\(\)/);
