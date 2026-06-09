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

export async function apiFetch(path: string, opts: RequestInit = {}, token?: string): Promise<any> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...opts,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(opts.headers || {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Unable to connect to server.', 0, null);
  }

  if (!res.ok) {
    const raw = await res.text();
    const parsed = await parseJsonSafely(raw);

    const detail = typeof parsed === 'object' && parsed ? (parsed as { detail?: unknown }).detail : undefined;
    const validationSummary =
      detail && typeof detail === 'object' && typeof (detail as { validation_summary?: unknown }).validation_summary === 'object'
        ? (detail as { validation_summary: { message?: unknown; issues?: unknown } }).validation_summary
        : null;
    const validationIssueLines = Array.isArray(validationSummary?.issues)
      ? validationSummary.issues.flatMap((issue: any) => Array.isArray(issue?.summaries) ? issue.summaries : [issue?.issue_type]).filter(Boolean)
      : [];

    const message =
      validationSummary && typeof validationSummary.message === 'string'
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

    throw new ApiError(message, res.status, parsed);
  }

  const data = res.status === 204 ? null : await parseJsonSafely(await res.text());
  if (data && typeof data === 'object' && 'success' in data && (data as { success: unknown }).success === false) {
    const message = typeof (data as { message?: unknown }).message === 'string' ? String((data as { message?: unknown }).message) : 'Request failed.';
    throw new ApiError(message, res.status, data);
  }
  return data;
}
