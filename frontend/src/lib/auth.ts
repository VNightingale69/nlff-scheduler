'use client';

export type UserRole = 'ADMIN' | 'LEAGUE_ADMIN' | 'SCHEDULING_ADMIN' | 'COMMUNITY_ADMIN';

export interface MissingScoreReminder {
  count: number;
  message: string;
  link: string;
  action_label: string;
  recent_games?: Array<{ game_id: string; game_date: string; kickoff_time: string; away_team_name: string; home_team_name: string }>;
}

export interface AuthUser {
  email: string;
  full_name?: string;
  role_name?: UserRole;
  organization_id: string | null;
  missing_score_reminder?: MissingScoreReminder | null;
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
  try { return JSON.parse(raw) as AuthUser; } catch { return null; }
};

export const setTokens = (accessToken: string, refreshToken: string, user?: AuthUser) => {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  if (user) {
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify({
      ...user,
      email: user.email,
      role_name: user.role_name,
      organization_id: user.organization_id ?? null,
      missing_score_reminder: user.missing_score_reminder ?? null,
    }));
  }
};

export const clearTokens = () => {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(AUTH_USER_KEY);
};
