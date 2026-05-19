'use client';
import Link from 'next/link';import { usePathname, useRouter } from 'next/navigation';import { clearTokens } from '@/lib/auth';
const links=[['organizations','Organizations'],['divisions','Divisions'],['host-locations','Host Locations'],['fields','Fields'],['teams','Teams'],['hosting-availability','Hosting Availability']];
export default function DashboardShell({children}:{children:React.ReactNode}){const p=usePathname(); const r=useRouter();
return <div className='min-h-screen md:flex'><aside className='w-full md:w-64 bg-slate-900 text-white p-4'><h2 className='font-bold mb-4'>NLFF Admin</h2><nav className='space-y-2'>{links.map(([k,l])=><Link key={k} className={`block rounded px-2 py-1 ${p.includes(k)?'bg-slate-700':'hover:bg-slate-800'}`} href={`/dashboard/${k}`}>{l}</Link>)}</nav><button className='mt-6 text-sm underline' onClick={()=>{clearTokens();r.push('/login')}}>Sign out</button></aside><main className='flex-1 p-4'>{children}</main></div>}
