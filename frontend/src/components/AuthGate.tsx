'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import DashboardShell from '@/components/DashboardShell';
import { apiFetch } from '@/lib/api';
import {
  clearTokens,
  getToken,
  reconcileClientStorageVersion,
  SESSION_EXPIRED_MESSAGE,
  setAuthUser,
  type AuthUser,
} from '@/lib/auth';

export type AuthSessionState = {
  authLoading: boolean;
  authResolved: boolean;
  currentUser: AuthUser | null;
  currentRole: string | null;
  isAuthenticated: boolean;
  accessToken: string | undefined;
};

const INITIAL_AUTH_SESSION: AuthSessionState = {
  authLoading: true,
  authResolved: false,
  currentUser: null,
  currentRole: null,
  isAuthenticated: false,
  accessToken: undefined,
};

const AuthSessionContext = createContext<AuthSessionState>(INITIAL_AUTH_SESSION);

export function useAuthSession() {
  return useContext(AuthSessionContext);
}

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

function ExpiredSessionShell() {
  return (
    <main className='flex min-h-screen items-center justify-center bg-slate-50 p-4'>
      <div className='max-w-md rounded border bg-white p-6 text-sm text-slate-700 shadow-sm'>
        {SESSION_EXPIRED_MESSAGE}
      </div>
    </main>
  );
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [authState, setAuthState] = useState<AuthSessionState>(INITIAL_AUTH_SESSION);

  useEffect(() => {
    let active = true;

    const resolveSession = async () => {
      reconcileClientStorageVersion();
      const token = getToken();
      if (!token) {
        clearTokens();
        if (active) {
          setAuthState({ ...INITIAL_AUTH_SESSION, authLoading: false, authResolved: true });
          router.replace('/login');
        }
        return;
      }

      try {
        const payload = await apiFetch('/auth/me', { cache: 'no-store' }, token);
        const resolvedUser = payload?.user as AuthUser | undefined;
        if (!resolvedUser) throw new Error('Current user response missing user');
        setAuthUser(resolvedUser);
        if (!active) return;
        setAuthState({
          authLoading: false,
          authResolved: true,
          currentUser: resolvedUser,
          currentRole: resolvedUser.role_name || null,
          isAuthenticated: true,
          accessToken: token,
        });
      } catch {
        clearTokens();
        if (active) {
          setAuthState({ ...INITIAL_AUTH_SESSION, authLoading: false, authResolved: true });
          router.replace('/login?session_expired=1');
        }
      }
    };

    resolveSession();
    return () => { active = false; };
  }, [router]);

  const contextValue = useMemo(() => authState, [authState]);

  if (!authState.authResolved || authState.authLoading) return <SessionLoadingShell />;
  if (!authState.isAuthenticated || !authState.currentUser) return <ExpiredSessionShell />;

  return (
    <AuthSessionContext.Provider value={contextValue}>
      <DashboardShell user={authState.currentUser}>{children}</DashboardShell>
    </AuthSessionContext.Provider>
  );
}
