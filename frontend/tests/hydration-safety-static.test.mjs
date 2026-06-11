import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const authSource = readFileSync(new URL('../src/lib/auth.ts', import.meta.url), 'utf8');
const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
const layoutSource = readFileSync(new URL('../src/app/(dashboard)/dashboard/layout.tsx', import.meta.url), 'utf8');
const adminLayoutSource = readFileSync(new URL('../src/app/(dashboard)/admin/layout.tsx', import.meta.url), 'utf8');
const gateSource = readFileSync(new URL('../src/components/AuthGate.tsx', import.meta.url), 'utf8');
const shellSource = readFileSync(new URL('../src/components/DashboardShell.tsx', import.meta.url), 'utf8');
const standingsSource = readFileSync(new URL('../src/app/(dashboard)/admin/standings/page.tsx', import.meta.url), 'utf8');
const organizationsSource = readFileSync(new URL('../src/app/(dashboard)/admin/organizations/page.tsx', import.meta.url), 'utf8');
const rulebookAdminSource = readFileSync(new URL('../src/app/(dashboard)/admin/rulebook/page.tsx', import.meta.url), 'utf8');
const publicScheduleSource = readFileSync(new URL('../src/app/schedule/page.tsx', import.meta.url), 'utf8');
const publicTournamentSource = readFileSync(new URL('../src/app/tournaments/page.tsx', import.meta.url), 'utf8');
const logoSource = readFileSync(new URL('../src/components/CommunityLogo.tsx', import.meta.url), 'utf8');
const bracketSource = readFileSync(new URL('../src/components/TournamentBracket.tsx', import.meta.url), 'utf8');

// Protected app routes render a deterministic AuthGate loading shell before reading browser storage.
assert.match(gateSource, /const INITIAL_AUTH_SESSION: AuthSessionState = \{\n\s*authLoading: true,\n\s*authResolved: false,\n\s*currentUser: null,\n\s*currentRole: null,\n\s*isAuthenticated: false,/);
assert.match(gateSource, /function SessionLoadingShell\(\)/);
assert.match(gateSource, /Loading session\.\.\./);
assert.match(gateSource, /useEffect\(\(\) => \{/);
assert.match(gateSource, /reconcileClientStorageVersion\(\)/);
assert.match(gateSource, /const token = getToken\(\)/);
assert.match(gateSource, /apiFetch\('\/auth\/me', \{ cache: 'no-store' \}, token\)/);
assert.match(gateSource, /setAuthUser\(resolvedUser\)/);
assert.match(gateSource, /authResolved: true,\n\s*currentUser: resolvedUser,/);
assert.match(gateSource, /if \(!authState\.authResolved \|\| authState\.authLoading\) return <SessionLoadingShell \/>/);
assert.match(gateSource, /SESSION_EXPIRED_MESSAGE/);
assert.match(layoutSource, /return <AuthGate>\{children\}<\/AuthGate>/);
assert.match(adminLayoutSource, /export \{ default \} from '..\/dashboard\/layout'/);

// Storage version mismatch clears only known app-owned auth/UI keys and then stores the current schema version.
assert.match(authSource, /APP_STORAGE_VERSION = process\.env\.NEXT_PUBLIC_APP_STORAGE_VERSION \|\| '2026-06-11-auth-hydration-v3'/);
assert.match(authSource, /APP_STORAGE_VERSION_KEY = 'nlff_app_storage_version'/);
for (const key of ['access_token', 'refresh_token', 'auth_user', 'auth_expires_at', 'token', 'current_user', 'user', 'role']) {
  assert.match(authSource, new RegExp(`'${key}'`));
}
for (const key of ['schedule_mode', 'optimization_preview', 'tournament_ui_cache', 'tournament_bracket_cache', 'feature_flags', 'sidebar_state', 'navigation_state', 'manualScheduleBuilderScheduleMode', 'logo_ui_state', 'rulebook_ui_state']) {
  assert.match(authSource, new RegExp(`'${key}'`));
}
assert.match(authSource, /window\.localStorage\.removeItem\(key\)/);
assert.match(authSource, /window\.sessionStorage\.removeItem\(key\)/);
assert.match(authSource, /clearVersionedClientState\(\);\n\s*window\.localStorage\.setItem\(APP_STORAGE_VERSION_KEY, APP_STORAGE_VERSION\)/);

// Invalid tokens clear stale auth state and use the friendly expired-session copy, never raw "Invalid token".
assert.match(apiSource, /SESSION_EXPIRED_MESSAGE/);
assert.match(apiSource, /handleExpiredSession\(\)/);
assert.doesNotMatch(apiSource, /throw new ApiError\('Invalid token'/);

// Sidebar waits for the resolved user from AuthGate and cannot render role-specific links from stale localStorage.
assert.match(shellSource, /DashboardShell\(\{ children, user \}: \{ children: React\.ReactNode; user: AuthUser \}\)/);
assert.doesNotMatch(shellSource, /getAuthUser/);
assert.match(shellSource, /const role = normalizeRoleName\(user\?\.role_name\)/);
assert.match(shellSource, /role === 'COMMUNITY_ADMIN'/);
assert.match(shellSource, /\(c\.roles as readonly string\[\]\)\.includes\(role\)/);
assert.match(gateSource, /<DashboardShell user=\{authState\.currentUser\}>\{children\}<\/DashboardShell>/);

// High-risk protected pages consume the resolved AuthGate session instead of cached user/role storage during render.
for (const source of [organizationsSource, rulebookAdminSource, standingsSource]) {
  assert.match(source, /useAuthSession\(\)/);
  assert.doesNotMatch(source, /const (user|authUser|canBuildTournament).*getAuthUser\(\)/);
}

// Public results, tournament, schedule, and logo rendering start from stable empty/loading state and update after effects/image events.
assert.match(standingsSource, /const \[payload, setPayload\] = useState<[^>]+ \| null>\(null\)/);
assert.match(standingsSource, /useEffect\(\(\) => \{ load\(\); \}, \[\]\)/);
assert.match(publicScheduleSource, /const \[games, setGames\] = useState<Game\[\]>\(\[\]\)/);
assert.match(publicScheduleSource, /const \[loading, setLoading\] = useState\(true\)/);
assert.match(publicScheduleSource, /<Suspense fallback=\{<div className='mx-auto max-w-6xl p-4'>Loading saved schedule\.\.\.<\/div>\}>/);
assert.match(publicTournamentSource, /const \[tournaments, setTournaments\] = useState<PublicTournament\[\]>\(\[\]\)/);
assert.match(publicTournamentSource, /const \[loading, setLoading\] = useState\(true\)/);
assert.match(bracketSource, /function TournamentBracket/);
assert.doesNotMatch(bracketSource, /Math\.random\(/);
assert.doesNotMatch(bracketSource, /crypto\.randomUUID\(/);
assert.match(logoSource, /const \[failedSrc, setFailedSrc\] = useState<string \| null>\(null\)/);
assert.match(logoSource, /onError=\{\(\) => \{ setFailedSrc\(resolvedSrc\); onLoadError\?\.\(resolvedSrc\); \}\}/);
assert.match(logoSource, /data-community-logo='fallback'/);

// Static audit: component render bodies must not synchronously initialize auth/user/role state from browser storage.
const srcRoot = new URL('../src', import.meta.url).pathname;
function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules') continue;
    const path = join(dir, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) yield* walk(path);
    else if (/\.(tsx|ts)$/.test(entry)) yield path;
  }
}
for (const path of walk(srcRoot)) {
  const rel = relative(srcRoot, path);
  const source = readFileSync(path, 'utf8');
  if (rel === 'lib/auth.ts' || rel === 'components/AuthGate.tsx') continue;
  assert.doesNotMatch(source, /^  const\s+\w+\s*=\s*getAuthUser\(\)/m, `${rel} must not read cached user during render`);
  assert.doesNotMatch(source, /^  const\s+\w+\s*=\s*getToken\(\)/m, `${rel} must not read cached token during render`);
  assert.doesNotMatch(source, /^  const\s+\w+\s*=\s*getToken\(\) \|\| undefined/m, `${rel} must not read cached token during render`);
}
