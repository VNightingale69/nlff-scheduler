'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import DashboardShell from '@/components/DashboardShell';
import { apiFetch } from '@/lib/api';
import { clearTokens, getToken, reconcileClientStorageVersion, setAuthUser, type AuthUser } from '@/lib/auth';

function SessionLoadingShell() {
  return (
    <div className='min-h-screen bg-slate-50 md:flex'>
      <aside className='w-full bg-slate-900 p-4 text-white md:w-64'>
        <div className='mb-4'>
          <div className='h-5 w-36 rounded bg-slate-700' />
          <div className='mt-2 h-3 w-44 rounded bg-slate-800' />
        </div>
      </aside>
      <main className='flex-1'>
        <header className='border-b bg-white px-4 py-3'>
          <div className='font-semibold'>Loading session...</div>
          <div className='text-sm text-slate-500'>Please wait while your session is verified.</div>
        </header>
        <section className='p-4'>
          <div className='rounded border bg-white p-6 text-sm text-slate-600'>Loading session...</div>
        </section>
      </main>
    </div>
  );
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;

    const resolveSession = async () => {
      reconcileClientStorageVersion();
      const token = getToken();
      if (!token) {
        clearTokens();
        router.replace('/login');
        return;
      }

      try {
        const payload = await apiFetch('/auth/me', { cache: 'no-store' }, token);
        const resolvedUser = payload?.user as AuthUser | undefined;
        if (!resolvedUser) throw new Error('Current user response missing user');
        setAuthUser(resolvedUser);
        if (!active) return;
        setUser(resolvedUser);
        setReady(true);
      } catch {
        clearTokens();
        if (active) router.replace('/login?session_expired=1');
      }
    };

    resolveSession();
    return () => { active = false; };
  }, [router]);

  if (!ready || !user) return <SessionLoadingShell />;

  return <DashboardShell user={user}>{children}</DashboardShell>;
}
