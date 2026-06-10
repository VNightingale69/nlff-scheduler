import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
const authSource = readFileSync(new URL('../src/lib/auth.ts', import.meta.url), 'utf8');
const loginSource = readFileSync(new URL('../src/app/(auth)/login/page.tsx', import.meta.url), 'utf8');
const shellSource = readFileSync(new URL('../src/components/DashboardShell.tsx', import.meta.url), 'utf8');

assert.match(authSource, /SESSION_EXPIRED_MESSAGE = 'Your session expired\. Please log in again\.'/);
assert.match(authSource, /AUTH_EXPIRES_AT_KEY = 'auth_expires_at'/);
assert.match(authSource, /isTokenNearExpiration = \(thresholdMs = 5 \* 60 \* 1000\)/);
assert.match(apiSource, /path\.startsWith\('\/auth\/refresh'\)/);
assert.match(apiSource, /await refreshAccessToken\(\)/);
assert.match(apiSource, /request\(path, opts, refreshedToken\)/);
assert.match(apiSource, /handleExpiredSession\(\)/);
assert.match(apiSource, /auth_invalid_token/);
assert.doesNotMatch(apiSource, /throw new ApiError\('Invalid token'/);
assert.match(loginSource, /session_expired'\) === '1'/);
assert.match(loginSource, /SESSION_EXPIRED_MESSAGE/);
assert.match(loginSource, /clearTokens\(\);\n      const data: any = await apiFetch\('\/auth\/login'/);
assert.match(loginSource, /setTokens\(data\.access_token, data\.refresh_token, buildAuthUser\(data\), data\.expires_at\)/);
assert.match(shellSource, /clearTokens\(\); router\.push\('\/login'\)/);
