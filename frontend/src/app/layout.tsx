import './globals.css';
import type { Metadata } from 'next';
import { ReactNode } from 'react';
import { APP_NAME, APP_SUBTITLE } from '@/config/branding';

export const metadata: Metadata = {
  title: APP_NAME,
  description: APP_SUBTITLE
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
