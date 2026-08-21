import type { Metadata } from 'next';
import type { ReactNode } from 'react';

export const metadata: Metadata = {
  title: 'Hosting Locations | Community Flag Football',
  description: 'Addresses and directions for Community Flag Football hosting sites.',
};

export default function LocationsLayout({ children }: { children: ReactNode }) {
  return children;
}
