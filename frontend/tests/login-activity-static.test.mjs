import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pageSource = readFileSync(new URL('../src/app/(dashboard)/admin/login-activity/page.tsx', import.meta.url), 'utf8');
const shellSource = readFileSync(new URL('../src/components/DashboardShell.tsx', import.meta.url), 'utf8');
const entitiesSource = readFileSync(new URL('../src/config/entities.ts', import.meta.url), 'utf8');

assert.match(pageSource, /Login Activity/);
assert.match(pageSource, /apiFetch\(`\/admin\/login-audit/);
assert.match(pageSource, /Newest attempts appear first/);
assert.match(pageSource, /Login Time/);
assert.match(pageSource, /User Email/);
assert.match(pageSource, /User Role/);
assert.match(pageSource, /Community/);
assert.match(pageSource, /Failure Reason/);
assert.match(pageSource, /IP Address/);
assert.match(pageSource, /Browser \/ User Agent/);
assert.match(pageSource, /resultOptions/);
assert.match(pageSource, /type='date'/);
assert.match(shellSource, /'login-activity'/);
assert.match(shellSource, /Security/);
assert.match(entitiesSource, /'login-activity': \{ title: 'Login Activity'/);
assert.match(entitiesSource, /roles: \['LEAGUE_ADMIN', 'SCHEDULING_ADMIN'\]/);
