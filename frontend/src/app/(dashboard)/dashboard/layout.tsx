'use client';
import { useEffect } from 'react';import { useRouter } from 'next/navigation';import DashboardShell from '@/components/DashboardShell';import { getToken } from '@/lib/auth';
export default function Layout({children}:{children:React.ReactNode}){const r=useRouter(); useEffect(()=>{if(!getToken()) r.push('/login')},[r]); return <DashboardShell>{children}</DashboardShell>}
