const RAW_API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const TRIMMED_API_URL = RAW_API_URL.replace(/\/$/, '');

export const API_URL = TRIMMED_API_URL.endsWith('/api') ? TRIMMED_API_URL : `${TRIMMED_API_URL}/api`;

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status: number, details: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export async function apiFetch(path: string, opts: RequestInit = {}, token?: string) {
  const res = await fetch(`${API_URL}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });

  if (!res.ok) {
    const raw = await res.text();
    let parsed: unknown = null;

    if (raw) {
      try {
        parsed = JSON.parse(raw);
      } catch {
        parsed = raw;
      }
    }

    const message =
      typeof parsed === 'object' && parsed && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : typeof parsed === 'string' && parsed
          ? parsed
          : 'Request failed';

    throw new ApiError(message, res.status, parsed);
  }

  return res.status === 204 ? null : res.json();
}
