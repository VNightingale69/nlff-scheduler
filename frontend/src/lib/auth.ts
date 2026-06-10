export type UserRole = 'LEAGUE_ADMIN' | 'COMMUNITY_ADMIN' | 'SCHEDULING_ADMIN' | string;
export type AuthUser = {
  id?: string;
  email: string;
  full_name?: string;
  role_name: UserRole;
  organization_id?: string | null;
};

export const SESSION_EXPIRED_MESSAGE = 'Your session expired. Please log in again.';
const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const AUTH_USER_KEY = 'auth_user';
const AUTH_EXPIRES_AT_KEY = 'auth_expires_at';

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

export const setTokens = (accessToken: string, refreshToken: string, user?: AuthUser, expiresAt?: string) => {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  const resolvedExpiresAt = expiresAt || decodeJwtExpiration(accessToken);
  if (resolvedExpiresAt) localStorage.setItem(AUTH_EXPIRES_AT_KEY, resolvedExpiresAt);
  else localStorage.removeItem(AUTH_EXPIRES_AT_KEY);
  if (user) {
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify({
      ...user,
      email: user.email,
      role_name: normalizeRoleName(user.role_name) as UserRole,
      organization_id: user.organization_id ?? null,
    }));
  }
};

export const clearTokens = () => {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
  localStorage.removeItem(AUTH_EXPIRES_AT_KEY);
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
