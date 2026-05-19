'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { clearTokens, getAuthUser } from '@/lib/auth';
import { ENTITIES } from '@/config/entities';

export default function DashboardShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const user = getAuthUser();
  const role = user?.role_name;
  const links = Object.entries(ENTITIES).filter(([, c]) => c.nav && (!c.roles || (role && c.roles.includes(role))));

  return <div className='min-h-screen bg-slate-50 md:flex'><aside className='w-full bg-slate-900 p-4 text-white md:w-64'><h2 className='mb-2 font-bold'>NLFF Admin</h2><p className='mb-4 text-xs text-slate-300'>{user?.email || 'Authenticated User'}</p><nav className='space-y-2'>{links.map(([key, cfg]) => <Link key={key} className={`block rounded px-2 py-1 ${pathname.includes(key) ? 'bg-slate-700' : 'hover:bg-slate-800'}`} href={`/dashboard/${key}`}>{cfg.title}</Link>)}</nav><button className='mt-6 text-sm underline' onClick={() => { clearTokens(); router.push('/login'); }}>Sign out</button></aside><main className='flex-1'><header className='border-b bg-white px-4 py-3 font-semibold'>Administrative Management</header><section className='p-4'>{children}</section></main></div>;
}
