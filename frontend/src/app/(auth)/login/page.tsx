'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, apiFetch } from '@/lib/api';
import { type AuthUser, setTokens } from '@/lib/auth';
import { APP_NAME, APP_SUBTITLE } from '@/config/branding';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const extractErrorMessage = (error: unknown): string => {
    if (!(error instanceof ApiError)) return 'Login failed. Please verify credentials.';

    if (error.status === 401) return 'Invalid credentials. Please verify your email and password.';

    const detail =
      typeof error.details === 'object' && error.details && 'detail' in error.details
        ? (error.details as { detail: unknown }).detail
        : null;

    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item !== 'object' || !item) return null;
          const path = 'loc' in item && Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.join('.')
            : 'field';
          const message = 'msg' in item ? String((item as { msg?: unknown }).msg) : 'Invalid value';
          return `${path}: ${message}`;
        })
        .filter(Boolean)
        .join(' | ');
    }

    if (typeof detail === 'string' && detail) return detail;
    return error.message || 'Login failed. Please verify credentials.';
  };

  const buildAuthUser = (data: any): AuthUser => {
    const responseUser = data?.user || {};

    return {
      ...responseUser,
      email: responseUser.email || data?.email || email,
      role_name: responseUser.role_name || data?.role_name,
      organization_id: responseUser.organization_id ?? data?.organization_id ?? null,
    };
  };

  const submit = async () => {
    try {
      setLoading(true); setError('');
      const data: any = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      if (!data?.access_token) throw new Error('Login response missing access token');
      setTokens(data.access_token, data.refresh_token, buildAuthUser(data));
      router.push('/dashboard');
    } catch (error) { setError(extractErrorMessage(error)); } finally { setLoading(false); }
  };

  return <main className='flex min-h-screen items-center justify-center p-4'><div className='w-full max-w-md rounded border bg-white p-6 shadow-sm'><h1 className='mb-1 text-xl font-bold'>{APP_NAME}</h1><p className='text-sm font-medium text-slate-700'>{APP_SUBTITLE}</p><p className='mb-4 mt-2 text-sm text-slate-600'>Sign in to manage scheduling setup entities.</p>{error && <p className='mb-3 text-sm text-rose-600'>{error}</p>}<input className='mb-2 w-full rounded border p-2' placeholder='Email' value={email} onChange={(e) => setEmail(e.target.value)} /><input className='mb-3 w-full rounded border p-2' type='password' placeholder='Password' value={password} onChange={(e) => setPassword(e.target.value)} /><button onClick={submit} disabled={loading} className='w-full rounded bg-slate-900 p-2 text-white'>{loading ? 'Signing in...' : 'Sign in'}</button></div></main>;
}
