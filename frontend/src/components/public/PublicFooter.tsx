import Link from 'next/link';

export default function PublicFooter() {
  return <footer className='mt-auto border-t border-slate-200 bg-white print:hidden'>
    <div className='mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-slate-600 sm:px-6'>
      <span>Community Flag Football Scheduler</span>
      <Link className='rounded underline decoration-slate-300 underline-offset-4 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-emerald-600' href='/login'>Admin Login</Link>
    </div>
  </footer>;
}
