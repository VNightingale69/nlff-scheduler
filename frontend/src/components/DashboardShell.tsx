'use client';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { type AuthUser, clearTokens, getAuthUser } from '@/lib/auth';
import { ENTITIES } from '@/config/entities';

export default function DashboardShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    setUser(getAuthUser());
  }, []);

  const role = user?.role_name;
  const navOrder = [
    'organizations',
    'divisions',
    'host-locations',
    'fields',
    'teams',
    'seasons',
    'weeks',
    'hosting-availability',
    'host-availability-matrix',
    'generated-slots',
    'schedule-readiness',
    'manual-schedule-builder',
    'schedule-management',
    'game-statuses',
    'games',
  ];
  const links = useMemo(
    () => navOrder
      .map((key) => [key, ENTITIES[key]] as const)
      .filter(([, c]) => c && c.nav && (!c.roles || (role && c.roles.includes(role)))),
    [role]
  );

  return <div className='min-h-screen bg-slate-50 md:flex'><aside className='w-full bg-slate-900 p-4 text-white md:w-64'><h2 className='mb-2 font-bold'>NLFF Admin</h2><p className='mb-4 text-xs text-slate-300'>{user?.email || 'Authenticated User'}</p><nav className='space-y-2'>{links.map(([key, cfg]) => <Link key={key} className={`block rounded px-2 py-1 ${pathname?.includes(`/admin/${key}`) || pathname === `/organizations` ? 'bg-slate-700' : 'hover:bg-slate-800'}`} href={`/admin/${key}`}>{cfg.title}</Link>)}
  <Link className='block rounded px-2 py-1 hover:bg-slate-800' href='/schedule'>Published Schedule</Link>
  </nav><button className='mt-6 text-sm underline' onClick={() => { clearTokens(); router.push('/login'); }}>Sign out</button></aside><main className='flex-1'><header className='border-b bg-white px-4 py-3 font-semibold'>Administrative Management</header><section className='p-4'>{children}</section></main></div>;
}
