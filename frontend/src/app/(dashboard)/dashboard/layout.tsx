'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import DashboardShell from '@/components/DashboardShell';
import { getToken } from '@/lib/auth';

export default function Layout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  useEffect(() => { if (!getToken()) router.push('/login'); }, [router]);
  return <DashboardShell>{children}</DashboardShell>;
}
