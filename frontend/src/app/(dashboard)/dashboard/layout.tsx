'use client';

import AuthGate from '@/components/AuthGate';

export default function Layout({ children }: { children: React.ReactNode }) {
  return <AuthGate>{children}</AuthGate>;
}
