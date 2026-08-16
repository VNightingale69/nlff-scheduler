'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

const links = [
  ['/', 'Home'],
  ['/schedule', 'Schedule'],
  ['/standings', 'Standings'],
  ['/scores', 'Scores'],
  ['/rulebook', 'Rulebook'],
] as const;

export default function PublicHeader() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return <header className='public-header border-b border-slate-200 bg-white print:hidden'>
    <div className='mx-auto w-full max-w-[1500px] px-4 py-3 sm:px-6 lg:px-8'>
      <div className='flex items-center justify-between gap-4'>
        <Link href='/' className='rounded text-lg font-extrabold tracking-tight text-slate-900 focus:outline-none focus:ring-2 focus:ring-emerald-600 focus:ring-offset-2'>Community Flag Football</Link>
        <div className='flex items-center gap-2'>
          <Link href='/login' className='rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-emerald-600 hover:text-emerald-800 focus:outline-none focus:ring-2 focus:ring-emerald-600 focus:ring-offset-2'>Admin Login</Link>
          <button type='button' className='rounded-md border p-2 md:hidden' aria-expanded={open} aria-controls='public-navigation' aria-label='Toggle navigation' onClick={() => setOpen(!open)}>
            <span aria-hidden='true' className='block text-xl leading-none'>☰</span>
          </button>
        </div>
      </div>
      <nav id='public-navigation' aria-label='Public navigation' className={`${open ? 'flex' : 'hidden'} mt-3 flex-col gap-1 border-t pt-3 md:flex md:flex-row md:border-0 md:pt-0`}>
        {links.map(([href, label]) => <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined} onClick={() => setOpen(false)} className={`rounded-md px-3 py-2 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-emerald-600 focus:ring-offset-2 ${pathname === href ? 'bg-emerald-50 text-emerald-900' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}`}>{label}</Link>)}
      </nav>
    </div>
  </header>;
}
