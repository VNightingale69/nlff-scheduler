'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { setTokens } from '@/lib/auth';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const submit = async () => {
    try {
      setLoading(true); setError('');
      const data = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
      setTokens(data.access_token, data.refresh_token, data.user || { email, role_name: data.role_name, organization_id: data.organization_id });
      router.push('/dashboard/organizations');
    } catch { setError('Login failed. Please verify credentials.'); } finally { setLoading(false); }
  };

  return <main className='flex min-h-screen items-center justify-center p-4'><div className='w-full max-w-md rounded border bg-white p-6 shadow-sm'><h1 className='mb-1 text-xl font-bold'>NLFF Administrative Login</h1><p className='mb-4 text-sm text-slate-600'>Sign in to manage scheduling setup entities.</p>{error && <p className='mb-3 text-sm text-rose-600'>{error}</p>}<input className='mb-2 w-full rounded border p-2' placeholder='Email' value={email} onChange={(e) => setEmail(e.target.value)} /><input className='mb-3 w-full rounded border p-2' type='password' placeholder='Password' value={password} onChange={(e) => setPassword(e.target.value)} /><button onClick={submit} disabled={loading} className='w-full rounded bg-slate-900 p-2 text-white'>{loading ? 'Signing in...' : 'Sign in'}</button></div></main>;
}
