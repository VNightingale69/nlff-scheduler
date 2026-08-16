import Link from 'next/link';
import { ReactNode } from 'react';

export default function PublicDashboardCard({ href, title, description, icon }: { href: string; title: string; description: string; icon: ReactNode }) {
  return <Link href={href} aria-label={`${title}: ${description}`} className='group flex min-h-64 flex-col items-center justify-center rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm transition hover:-translate-y-1 hover:border-emerald-300 hover:shadow-lg focus:outline-none focus:ring-4 focus:ring-emerald-600 focus:ring-offset-4'>
    <span aria-hidden='true' className='mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700 transition group-hover:bg-emerald-100'>{icon}</span>
    <h2 className='text-2xl font-bold text-slate-900'>{title}</h2>
    <p className='mt-3 max-w-sm leading-relaxed text-slate-600'>{description}</p>
  </Link>;
}
