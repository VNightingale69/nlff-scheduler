'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

const links = [
  ['/', 'Home'],
  ['/schedule', 'Schedule'],
  ['/standings', 'Standings'],
  ['/scores', 'Scores'],
  ['/locations', 'Locations'],
  ['/rulebook', 'Rulebook'],
] as const;

export default function PublicHeader() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return <header className='public-header border-b border-slate-200 bg-white print:hidden'>
    <div className='mx-auto w-full max-w-[1500px] px-4 py-3 sm:px-6 lg:px-8'>
      <div className='flex items-center justify-between gap-3'>
        <Link href='/' className='min-w-0 rounded text-base font-extrabold tracking-tight text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2 sm:text-lg'>Community Flag Football</Link>
        <nav aria-label='Public navigation' className='hidden items-center gap-1 md:flex'>
          {links.map(([href, label]) => <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined} className={`rounded-md px-3 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2 ${pathname === href ? 'bg-emerald-50 text-emerald-900' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}`}>{label}</Link>)}
        </nav>
        <div className='flex items-center gap-2'>
          <Link href='/login' className='hidden rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-emerald-600 hover:text-emerald-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2 min-[390px]:block'>Admin Login</Link>
          <button type='button' className='flex h-11 w-11 items-center justify-center rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2 md:hidden' aria-expanded={open} aria-controls='mobile-public-navigation' aria-label='Toggle navigation' onClick={() => setOpen(!open)}>
            <svg aria-hidden='true' viewBox='0 0 24 24' className='h-6 w-6' fill='none' stroke='currentColor' strokeWidth='2' strokeLinecap='round'><path d={open ? 'M6 6l12 12M18 6L6 18' : 'M4 7h16M4 12h16M4 17h16'} /></svg>
          </button>
        </div>
      </div>
      <nav id='mobile-public-navigation' aria-label='Mobile public navigation' className={`${open ? 'flex' : 'hidden'} mt-3 flex-col gap-1 border-t border-slate-200 pt-3 md:hidden`}>
        {links.map(([href, label]) => <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined} onClick={() => setOpen(false)} className={`rounded-md px-3 py-2 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-600 focus:ring-offset-2 ${pathname === href ? 'bg-emerald-50 text-emerald-900' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}`}>{label}</Link>)}
        <Link href='/login' onClick={() => setOpen(false)} className='rounded-md px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 min-[390px]:hidden'>Admin Login</Link>
      </nav>
    </div>
  </header>;
}
