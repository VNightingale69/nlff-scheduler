import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import PublicDashboardCard from '@/components/public/PublicDashboardCard';
import PublicLayout from '@/components/public/PublicLayout';

export const metadata: Metadata = { title: 'Community Flag Football', description: 'View flag football schedules, scores, standings and league rules.' };

const Icon = ({ children }: { children: ReactNode }) => <svg viewBox='0 0 24 24' width='36' height='36' fill='none' stroke='currentColor' strokeWidth='1.8' strokeLinecap='round' strokeLinejoin='round'>{children}</svg>;

export default function Home() {
  return <PublicLayout><main className='mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16'>
    <section className='mb-10 text-center' aria-labelledby='dashboard-title'>
      <p className='mb-3 text-sm font-bold uppercase tracking-[0.22em] text-emerald-700'>Your league. One place.</p>
      <h1 id='dashboard-title' className='text-4xl font-extrabold tracking-tight text-slate-950 sm:text-5xl'>Community Flag Football</h1>
      <p className='mt-4 text-lg text-slate-600'>Schedules <span aria-hidden='true'>•</span> Scores <span aria-hidden='true'>•</span> Standings <span aria-hidden='true'>•</span> Rules</p>
    </section>
    <nav aria-label='Dashboard' className='grid grid-cols-1 gap-6 md:grid-cols-2'>
      <PublicDashboardCard href='/schedule' title='Schedule' description='View game dates, times, fields, teams and hosting locations.' icon={<Icon><path d='M3 5h18v16H3zM8 3v4M16 3v4M3 10h18' /></Icon>} />
      <PublicDashboardCard href='/standings' title='Standings' description='View division standings, team records and rankings.' icon={<Icon><path d='M8 4h8v5a4 4 0 0 1-8 0zM8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4M12 13v5M8 21h8M9 18h6' /></Icon>} />
      <PublicDashboardCard href='/scores' title='Scores' description='View completed games and recent scores.' icon={<Icon><path d='M4 5h16v14H4zM8 9h2v3H8zM14 9h2v3h-2zM8 16h8' /></Icon>} />
      <PublicDashboardCard href='/rulebook' title='Rulebook' description='View league rules and division-specific requirements.' icon={<Icon><path d='M4 4h6a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H4zM20 4h-4a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h4z' /></Icon>} />
    </nav>
  </main></PublicLayout>;
}
