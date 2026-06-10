'use client';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { type AuthUser, clearTokens, getAuthUser, normalizeRoleName } from '@/lib/auth';
import { ENTITIES } from '@/config/entities';
import { APP_NAME, APP_SUBTITLE } from '@/config/branding';

export default function DashboardShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    setUser(getAuthUser());
  }, []);

  const role = normalizeRoleName(user?.role_name) as AuthUser['role_name'];
  const navOrder = role === 'COMMUNITY_ADMIN'
    ? ['organizations', 'teams', 'host-locations', 'fields', 'hosting-availability', 'score-entry', 'standings', 'rulebook']
    : [
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
      'standings',
      'tournaments',
      'scores',
      'scores/flagged',
      'scores/missing',
      'rulebook',
    ];
  const communityTitles: Record<string, string> = {
    organizations: 'My Community',
    teams: 'My Teams',
    'host-locations': 'My Host Locations',
    fields: 'My Fields',
    'hosting-availability': 'My Hosting Availability',
    'score-entry': 'Score Entry',
    standings: 'Results & Standings',
    rulebook: 'Rulebook',
  };
  const links = useMemo(
    () => navOrder
      .map((key) => [key, ENTITIES[key]] as const)
      .filter(([, c]) => c && c.nav && (!c.roles || (role && (c.roles as readonly string[]).includes(role)))),
    [navOrder, role]
  );

  return <div className='min-h-screen bg-slate-50 md:flex'><aside className='w-full bg-slate-900 p-4 text-white md:w-64'><div className='mb-4'><h2 className='font-bold leading-tight'>{APP_NAME}</h2><p className='text-xs text-slate-300'>{APP_SUBTITLE}</p></div><p className='mb-4 text-xs text-slate-300'>{user?.email || 'Authenticated User'}</p><nav className='space-y-2'>{links.map(([key, cfg]) => {
    const title = role === 'COMMUNITY_ADMIN' ? communityTitles[key] || cfg.title : cfg.title;
    const isAdminScores = role !== 'COMMUNITY_ADMIN' && key.startsWith('scores');
    const isCommunityScores = role === 'COMMUNITY_ADMIN' && key === 'score-entry';
    const navTitle = key === 'scores' ? 'Score Management' : key === 'scores/flagged' ? 'Flagged Scores' : key === 'scores/missing' ? 'Missing Scores' : title;
    return <div key={key}>{key === 'host-availability-matrix' ? <div className='px-2 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400'>Scheduling</div> : null}{(key === 'scores' || isCommunityScores) ? <div className='px-2 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400'>Scores</div> : null}<Link className={`block rounded px-2 py-1 ${pathname?.includes(`/admin/${key}`) || pathname === `/organizations` ? 'bg-slate-700' : isAdminScores ? 'ml-3 hover:bg-slate-800' : 'hover:bg-slate-800'}`} href={`/admin/${key}`}>{navTitle}</Link></div>;
  })}
  <Link className='block rounded px-2 py-1 hover:bg-slate-800' href='/schedule'>Published Schedule</Link>
  <Link className='block rounded px-2 py-1 hover:bg-slate-800' href='/rulebook'>Public Rulebook</Link>
  </nav><button className='mt-6 text-sm underline' onClick={() => { clearTokens(); router.push('/login'); }}>Sign out</button></aside><main className='flex-1'><header className='border-b bg-white px-4 py-3'><div className='font-semibold'>{role === 'COMMUNITY_ADMIN' ? 'Community Management' : 'Community Flag Scheduler Administration'}</div><div className='text-sm text-slate-500'>{APP_SUBTITLE}</div></header><section className='p-4'>{children}</section></main></div>;
}
