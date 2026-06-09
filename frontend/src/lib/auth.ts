'use client';

export type UserRole = 'ADMIN' | 'LEAGUE_ADMIN' | 'SCHEDULING_ADMIN' | 'COMMUNITY_ADMIN';

export interface AuthUser {
  email: string;
  full_name?: string;
  role_name?: UserRole;
  organization_id: string | null;
}


export function normalizeRoleName(roleName: unknown): UserRole | string {
  const normalized = String(roleName || '')
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  if (normalized === 'ADMIN') return 'LEAGUE_ADMIN';
  if (normalized === 'SCHEDULING_ADMINISTRATOR') return 'SCHEDULING_ADMIN';
  if (normalized === 'COMMUNITY_SCHEDULER') return 'COMMUNITY_ADMIN';
  return normalized;
}

export function canManageSchedule(user: AuthUser | null | undefined): boolean {
  const role = normalizeRoleName(user?.role_name);
  return role === 'LEAGUE_ADMIN' || role === 'SCHEDULING_ADMIN';
}

export function canManageScores(user: AuthUser | null | undefined): boolean {
  const role = normalizeRoleName(user?.role_name);
  return role === 'LEAGUE_ADMIN' || role === 'SCHEDULING_ADMIN';
}

export function canSubmitCommunityScores(user: AuthUser | null | undefined): boolean {
  return normalizeRoleName(user?.role_name) === 'COMMUNITY_ADMIN';
}

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';
const AUTH_USER_KEY = 'auth_user';

export const getToken = () => (typeof window === 'undefined' ? '' : localStorage.getItem(ACCESS_TOKEN_KEY) || '');
export const getRefreshToken = () => (typeof window === 'undefined' ? '' : localStorage.getItem(REFRESH_TOKEN_KEY) || '');

export const getAuthUser = (): AuthUser | null => {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(AUTH_USER_KEY);
  if (!raw) return null;
  try {
    const user = JSON.parse(raw) as AuthUser;
    return { ...user, role_name: normalizeRoleName(user.role_name) as UserRole };
  } catch { return null; }
};

export const setTokens = (accessToken: string, refreshToken: string, user?: AuthUser) => {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
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
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
};
