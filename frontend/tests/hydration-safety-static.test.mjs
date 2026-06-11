import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const authSource = readFileSync(new URL('../src/lib/auth.ts', import.meta.url), 'utf8');
const apiSource = readFileSync(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
const layoutSource = readFileSync(new URL('../src/app/(dashboard)/dashboard/layout.tsx', import.meta.url), 'utf8');
const adminLayoutSource = readFileSync(new URL('../src/app/(dashboard)/admin/layout.tsx', import.meta.url), 'utf8');
const shellSource = readFileSync(new URL('../src/components/DashboardShell.tsx', import.meta.url), 'utf8');
const standingsSource = readFileSync(new URL('../src/app/(dashboard)/admin/standings/page.tsx', import.meta.url), 'utf8');
const publicScheduleSource = readFileSync(new URL('../src/app/schedule/page.tsx', import.meta.url), 'utf8');
const publicTournamentSource = readFileSync(new URL('../src/app/tournaments/page.tsx', import.meta.url), 'utf8');
const logoSource = readFileSync(new URL('../src/components/CommunityLogo.tsx', import.meta.url), 'utf8');
const bracketSource = readFileSync(new URL('../src/components/TournamentBracket.tsx', import.meta.url), 'utf8');

// App loads with empty storage or stale auth storage by rendering a deterministic protected-route shell first.
assert.match(layoutSource, /function SessionLoadingShell\(\)/);
assert.match(layoutSource, /Loading session\.\.\./);
assert.match(layoutSource, /if \(!ready \|\| !user\) return <SessionLoadingShell \/>/);
assert.match(layoutSource, /const \[ready, setReady\] = useState\(false\)/);
assert.match(adminLayoutSource, /export \{ default \} from '..\/dashboard\/layout'/);

// Storage version mismatch clears only known auth/app UI keys and then stores the current schema version.
assert.match(authSource, /APP_STORAGE_VERSION = process\.env\.NEXT_PUBLIC_APP_STORAGE_VERSION \|\| '2026-06-10-auth-v2'/);
assert.match(authSource, /APP_STORAGE_VERSION_KEY = 'nlff_app_storage_version'/);
assert.match(authSource, /const AUTH_STORAGE_KEYS = \[/);
for (const key of ['access_token', 'refresh_token', 'auth_user', 'auth_expires_at', 'token', 'current_user', 'user', 'role']) {
  assert.match(authSource, new RegExp(`'${key}'`));
}
for (const key of ['schedule_mode', 'optimization_preview', 'tournament_ui_cache', 'tournament_bracket_cache', 'feature_flags', 'sidebar_state', 'navigation_state']) {
  assert.match(authSource, new RegExp(`'${key}'`));
}
assert.match(authSource, /window\.localStorage\.removeItem\(key\)/);
assert.match(authSource, /window\.sessionStorage\.removeItem\(key\)/);
assert.match(authSource, /reconcileClientStorageVersion/);
assert.match(authSource, /clearVersionedClientState\(\);\n\s*window\.localStorage\.setItem\(APP_STORAGE_VERSION_KEY, APP_STORAGE_VERSION\)/);

// Stored auth is not trusted for protected markup: token is read after mount, current user is fetched, and only then children render.
assert.match(layoutSource, /useEffect\(\(\) => \{/);
assert.match(layoutSource, /reconcileClientStorageVersion\(\)/);
assert.match(layoutSource, /const token = getToken\(\)/);
assert.match(layoutSource, /apiFetch\('\/auth\/me', \{ cache: 'no-store' \}, token\)/);
assert.match(layoutSource, /setAuthUser\(resolvedUser\)/);
assert.match(layoutSource, /setReady\(true\)/);
assert.match(layoutSource, /router\.replace\('\/login'\)/);
assert.match(layoutSource, /router\.replace\('\/login\?session_expired=1'\)/);
assert.match(apiSource, /SESSION_EXPIRED_MESSAGE/);
assert.match(apiSource, /handleExpiredSession\(\)/);
assert.doesNotMatch(apiSource, /throw new ApiError\('Invalid token'/);

// Sidebar waits for the resolved user from the layout and cannot render role-specific links from stale localStorage.
assert.match(shellSource, /DashboardShell\(\{ children, user \}: \{ children: React\.ReactNode; user: AuthUser \}\)/);
assert.doesNotMatch(shellSource, /getAuthUser/);
assert.match(shellSource, /const role = normalizeRoleName\(user\?\.role_name\)/);
assert.match(shellSource, /role === 'COMMUNITY_ADMIN'/);
assert.match(shellSource, /\(c\.roles as readonly string\[\]\)\.includes\(role\)/);
assert.match(layoutSource, /<DashboardShell user=\{user\}>\{children\}<\/DashboardShell>/);

// Results, tournaments, schedule, and logo rendering start from stable empty/loading state and update only after effects or image events.
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
