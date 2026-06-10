import {
  clearTokens,
  getRefreshToken,
  getToken,
  isTokenNearExpiration,
  redirectToLoginForExpiredSession,
  SESSION_EXPIRED_MESSAGE,
  setTokens,
} from '@/lib/auth';

const RAW_API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const TRIMMED_API_URL = RAW_API_URL.replace(/\/$/, '');

export const API_URL = TRIMMED_API_URL.endsWith('/api') ? TRIMMED_API_URL : `${TRIMMED_API_URL}/api`;

export class ApiError extends Error {
  status: number;
  details: unknown;
  detail?: unknown;
  dependencies?: unknown;

  constructor(message: string, status: number, details: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;

    if (details && typeof details === 'object') {
      if ('detail' in details) this.detail = (details as { detail: unknown }).detail;
      if ('dependencies' in details) this.dependencies = (details as { dependencies: unknown }).dependencies;
    }
  }
}

async function parseJsonSafely(raw: string): Promise<unknown> {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function isAuthFailure(status: number, parsed: unknown, raw = ''): boolean {
  const lowerRaw = raw.toLowerCase();
  const error = parsed && typeof parsed === 'object' && 'error' in parsed ? String((parsed as { error?: unknown }).error) : '';
  const message = parsed && typeof parsed === 'object' && 'message' in parsed ? String((parsed as { message?: unknown }).message) : '';
  const detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? (parsed as { detail?: unknown }).detail : undefined;
  const detailMessage = typeof detail === 'string'
    ? detail
    : detail && typeof detail === 'object' && 'message' in detail
      ? String((detail as { message?: unknown }).message)
      : '';
  const combined = `${error} ${message} ${detailMessage} ${lowerRaw}`.toLowerCase();
  return status === 401 && (
    combined.includes('auth_invalid_token')
    || combined.includes('token expired')
    || combined.includes('invalid token')
    || combined.includes('not authenticated')
    || combined.includes('signature verification failed')
  );
}

function authHeaders(opts: RequestInit, token?: string): HeadersInit {
  const headers = new Headers(opts.headers);
  const authToken = token || getToken();
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`);
  if (!(opts.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return headers;
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (res) => {
        const raw = await res.text();
        const parsed: any = await parseJsonSafely(raw);
        if (!res.ok || !parsed?.access_token) return null;
        setTokens(parsed.access_token, parsed.refresh_token, parsed.user, parsed.expires_at);
        return parsed.access_token as string;
      })
      .catch(() => null)
      .finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

function handleExpiredSession(): never {
  clearTokens();
  redirectToLoginForExpiredSession();
  throw new ApiError(SESSION_EXPIRED_MESSAGE, 401, { error: 'auth_invalid_token', message: SESSION_EXPIRED_MESSAGE });
}

async function request(path: string, opts: RequestInit, token?: string): Promise<{ res: Response; raw: string; parsed: unknown }> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...opts,
      headers: authHeaders(opts, token),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Unable to connect to server.', 0, null);
  }
  const raw = await res.text();
  return { res, raw, parsed: await parseJsonSafely(raw) };
}

function messageFromError(parsed: unknown): string {
  const detail = typeof parsed === 'object' && parsed ? (parsed as { detail?: unknown }).detail : undefined;
  const validationSummary =
    detail && typeof detail === 'object' && typeof (detail as { validation_summary?: unknown }).validation_summary === 'object'
      ? (detail as { validation_summary: { message?: unknown; issues?: unknown } }).validation_summary
      : null;
  const validationIssueLines = Array.isArray(validationSummary?.issues)
    ? validationSummary.issues.flatMap((issue: any) => Array.isArray(issue?.summaries) ? issue.summaries : [issue?.issue_type]).filter(Boolean)
    : [];

  return validationSummary && typeof validationSummary.message === 'string'
    ? [validationSummary.message, ...validationIssueLines.map((line: unknown) => `• ${String(line)}`)].join('\n')
    : typeof detail === 'string'
      ? detail
      : detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string'
        ? (detail as { message: string }).message
        : typeof parsed === 'object' && parsed && typeof (parsed as { message?: unknown }).message === 'string'
          ? (parsed as { message: string }).message
          : parsed
            ? 'Request failed. Please review the validation summary and try again.'
            : 'Request failed';
}

export async function apiFetch(path: string, opts: RequestInit = {}, token?: string): Promise<any> {
  const authEndpoint = path.startsWith('/auth/login') || path.startsWith('/auth/refresh');
  let requestToken = token || getToken();

  if (!authEndpoint && requestToken && isTokenNearExpiration()) {
    requestToken = (await refreshAccessToken()) || requestToken;
  }

  let { res, raw, parsed } = await request(path, opts, requestToken);
  const shouldTryRefresh = !authEndpoint && isAuthFailure(res.status, parsed, raw);
  if (shouldTryRefresh) {
    const refreshedToken = await refreshAccessToken();
    if (!refreshedToken) handleExpiredSession();
    ({ res, raw, parsed } = await request(path, opts, refreshedToken));
    if (isAuthFailure(res.status, parsed, raw)) handleExpiredSession();
  }

  if (!res.ok) {
    throw new ApiError(messageFromError(parsed), res.status, parsed);
  }

  const data = res.status === 204 ? null : parsed;
  if (data && typeof data === 'object' && 'success' in data && (data as { success: unknown }).success === false) {
    const message = typeof (data as { message?: unknown }).message === 'string' ? String((data as { message?: unknown }).message) : 'Request failed.';
    throw new ApiError(message, res.status, data);
  }
  return data;
}
