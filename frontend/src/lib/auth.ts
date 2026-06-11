export type UserRole = 'LEAGUE_ADMIN' | 'COMMUNITY_ADMIN' | 'SCHEDULING_ADMIN' | string;
export type AuthUser = {
  id?: string;
  email: string;
  full_name?: string;
  role_name: UserRole;
  organization_id?: string | null;
};

export const SESSION_EXPIRED_MESSAGE = 'Your session expired. Please log in again.';
export const APP_STORAGE_VERSION = process.env.NEXT_PUBLIC_APP_STORAGE_VERSION || '2026-06-11-auth-hydration-v3';
export const APP_STORAGE_VERSION_KEY = 'nlff_app_storage_version';
const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const AUTH_USER_KEY = 'auth_user';
const AUTH_EXPIRES_AT_KEY = 'auth_expires_at';

const AUTH_STORAGE_KEYS = [
  ACCESS_TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  AUTH_USER_KEY,
  AUTH_EXPIRES_AT_KEY,
  'token',
  'current_user',
  'user',
  'role',
] as const;

const UI_CACHE_STORAGE_KEYS = [
  'schedule_mode',
  'optimization_preview',
  'tournament_ui_cache',
  'tournament_bracket_cache',
  'feature_flags',
  'sidebar_state',
  'navigation_state',
  'scheduleViewMode',
  'manualScheduleBuilderScheduleMode',
  'optimizationPreview',
  'optimization-preview',
  'turfOptimizationState',
  'turf-optimization-state',
  'scheduleStateLabel',
  'old_tournament_view_cache',
  'old_schedule_view_cache',
  'logo_ui_state',
  'rulebook_ui_state',
] as const;

const VERSIONED_STORAGE_KEYS = [...AUTH_STORAGE_KEYS, ...UI_CACHE_STORAGE_KEYS] as const;

export function normalizeRoleName(roleName?: string | null): string {
  if (!roleName) return '';
  const normalized = String(roleName)
    .trim()
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase();
  if (normalized === 'ADMIN') return 'LEAGUE_ADMIN';
  if (normalized === 'SCHEDULING_ADMINISTRATOR') return 'SCHEDULING_ADMIN';
  if (normalized === 'COMMUNITY_SCHEDULER') return 'COMMUNITY_ADMIN';
  return normalized;
}

export function canManageSchedule(user: AuthUser | null | undefined): boolean {
  const role = normalizeRoleName(user?.role_name);
  return role === 'LEAGUE_ADMIN' || role === 'SCHEDULING_ADMIN';
}

export function canPublishSchedule(user: AuthUser | null | undefined): boolean {
  return canManageSchedule(user);
}

export function canUnpublishSchedule(user: AuthUser | null | undefined): boolean {
  return canPublishSchedule(user);
}

export function canModifySchedule(user: AuthUser | null | undefined): boolean {
  return canManageSchedule(user);
}

export function canManageScores(user: AuthUser | null | undefined): boolean {
  const role = normalizeRoleName(user?.role_name);
  return role === 'LEAGUE_ADMIN' || role === 'SCHEDULING_ADMIN';
}

export function canSubmitCommunityScores(user: AuthUser | null | undefined): boolean {
  return normalizeRoleName(user?.role_name) === 'COMMUNITY_ADMIN';
}

function readLocalStorage(key: string): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(key) || '';
}

function removeClientStorageKey(key: string) {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(key);
  window.sessionStorage.removeItem(key);
}

function decodeJwtExpiration(token: string): string {
  try {
    const encodedPayload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const paddedPayload = encodedPayload.padEnd(encodedPayload.length + ((4 - (encodedPayload.length % 4)) % 4), '=');
    const payload = JSON.parse(atob(paddedPayload));
    if (typeof payload.exp === 'number') return new Date(payload.exp * 1000).toISOString();
  } catch {
    return '';
  }
  return '';
}

export const getToken = () => readLocalStorage(ACCESS_TOKEN_KEY);
export const getRefreshToken = () => readLocalStorage(REFRESH_TOKEN_KEY);
export const getTokenExpiresAt = () => readLocalStorage(AUTH_EXPIRES_AT_KEY);

export const getAuthUser = (): AuthUser | null => {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(AUTH_USER_KEY);
  if (!raw) return null;
  try {
    const user = JSON.parse(raw) as AuthUser;
    return { ...user, role_name: normalizeRoleName(user.role_name) as UserRole };
  } catch { return null; }
};

export const setAuthUser = (user: AuthUser) => {
  if (typeof window === 'undefined') return;
  localStorage.setItem(AUTH_USER_KEY, JSON.stringify({
    ...user,
    email: user.email,
    role_name: normalizeRoleName(user.role_name) as UserRole,
    organization_id: user.organization_id ?? null,
  }));
};

export const setTokens = (accessToken: string, refreshToken: string, user?: AuthUser, expiresAt?: string) => {
  localStorage.setItem(APP_STORAGE_VERSION_KEY, APP_STORAGE_VERSION);
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  const resolvedExpiresAt = expiresAt || decodeJwtExpiration(accessToken);
  if (resolvedExpiresAt) localStorage.setItem(AUTH_EXPIRES_AT_KEY, resolvedExpiresAt);
  else localStorage.removeItem(AUTH_EXPIRES_AT_KEY);
  if (user) setAuthUser(user);
};

export const clearTokens = () => {
  if (typeof window === 'undefined') return;
  AUTH_STORAGE_KEYS.forEach(removeClientStorageKey);
};

export const clearVersionedClientState = () => {
  if (typeof window === 'undefined') return;
  VERSIONED_STORAGE_KEYS.forEach(removeClientStorageKey);
};

export const reconcileClientStorageVersion = () => {
  if (typeof window === 'undefined') return;
  const storedVersion = window.localStorage.getItem(APP_STORAGE_VERSION_KEY);
  if (storedVersion !== APP_STORAGE_VERSION) {
    clearVersionedClientState();
    window.localStorage.setItem(APP_STORAGE_VERSION_KEY, APP_STORAGE_VERSION);
  }
};

export const isTokenNearExpiration = (thresholdMs = 5 * 60 * 1000): boolean => {
  const expiresAt = getTokenExpiresAt();
  if (!expiresAt) return false;
  const expiresAtMs = Date.parse(expiresAt);
  if (Number.isNaN(expiresAtMs)) return true;
  return expiresAtMs - Date.now() <= thresholdMs;
};

export const redirectToLoginForExpiredSession = () => {
  if (typeof window === 'undefined') return;
  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.assign(`/login?session_expired=1&return_to=${encodeURIComponent(returnTo)}`);
};
