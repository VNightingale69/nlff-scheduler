import type { Metadata } from 'next';
import type { SVGProps } from 'react';
import PublicDashboardCard, { type PublicDashboardCardVariant } from '@/components/public/PublicDashboardCard';
import PublicLayout from '@/components/public/PublicLayout';

export const metadata: Metadata = { title: 'Community Flag Football', description: 'View flag football schedules, scores, standings and league rules.' };

const iconProps = {
  viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.9,
  strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
};

const CalendarIcon = (props: SVGProps<SVGSVGElement>) => <svg {...iconProps} {...props}><path d='M3 5h18v16H3zM8 3v4M16 3v4M3 10h18' /></svg>;
const TrophyIcon = (props: SVGProps<SVGSVGElement>) => <svg {...iconProps} {...props}><path d='M8 4h8v5a4 4 0 0 1-8 0zM8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4M12 13v5M8 21h8M9 18h6' /></svg>;
const ScoreboardIcon = (props: SVGProps<SVGSVGElement>) => <svg {...iconProps} {...props}><path d='M4 5h16v14H4zM8 9h2v3H8zM14 9h2v3h-2zM8 16h8' /></svg>;
const BookOpenIcon = (props: SVGProps<SVGSVGElement>) => <svg {...iconProps} {...props}><path d='M4 4h6a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H4zM20 4h-4a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h4z' /></svg>;
const MapPinIcon = (props: SVGProps<SVGSVGElement>) => <svg {...iconProps} {...props}><path d='M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0z' /><circle cx='12' cy='10' r='2.5' /></svg>;

const dashboardLinks = [
  { href: '/schedule', title: 'Schedule', description: 'View game dates, times, fields, teams and hosting locations.', icon: CalendarIcon, variant: 'green' },
  { href: '/standings', title: 'Standings', description: 'View division standings, team records and rankings.', icon: TrophyIcon, variant: 'blue' },
  { href: '/scores', title: 'Scores', description: 'View completed games and recent scores.', icon: ScoreboardIcon, variant: 'orange' },
  { href: '/locations', title: 'Locations', description: 'Find hosting site addresses, arrival notes and directions.', icon: MapPinIcon, variant: 'green' },
  { href: '/rulebook', title: 'Rulebook', description: 'View league rules and division-specific requirements.', icon: BookOpenIcon, variant: 'purple' },
] satisfies Array<{ href: string; title: string; description: string; icon: typeof CalendarIcon; variant: PublicDashboardCardVariant }>;

export default function Home() {
  return (
    <PublicLayout>
      <main className='mx-auto w-full max-w-7xl px-4 py-5 sm:px-6 sm:py-8 lg:px-8 lg:py-12'>
        <section className='relative mb-5 overflow-hidden rounded-3xl bg-gradient-to-br from-emerald-950 via-emerald-800 to-teal-700 px-6 py-7 text-white shadow-lg sm:mb-8 sm:px-10 sm:py-10 lg:px-12' aria-labelledby='dashboard-title'>
          <div aria-hidden='true' className='absolute -right-16 -top-24 h-64 w-64 rounded-full border-[28px] border-white/5' />
          <div aria-hidden='true' className='absolute inset-y-0 left-1/2 hidden border-l border-dashed border-white/15 sm:block' />
          <div className='relative'>
            <p className='text-xs font-extrabold uppercase tracking-[0.22em] text-emerald-100 sm:text-sm'>Your league. One place.</p>
            <h1 id='dashboard-title' className='mt-2 max-w-3xl text-3xl font-black tracking-tight sm:text-4xl lg:text-5xl'>Community Flag Football</h1>
            <p className='mt-3 text-sm font-medium text-emerald-50 sm:text-base'>Schedules <span aria-hidden='true'>•</span> Scores <span aria-hidden='true'>•</span> Standings <span aria-hidden='true'>•</span> Rules</p>
          </div>
        </section>
        <nav aria-label='Public dashboard' className='grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 sm:gap-4 lg:grid-cols-3'>
          {dashboardLinks.map(link => <PublicDashboardCard key={link.href} {...link} />)}
        </nav>
      </main>
    </PublicLayout>
  );
}
