import type { Metadata } from 'next';
import PublicLayout from '@/components/public/PublicLayout';
import PublicResults from '@/components/public/PublicResults';

export const metadata: Metadata = { title: 'Standings | Community Flag Football' };
export default function StandingsPage() { return <PublicLayout><main className='mx-auto max-w-6xl px-4 py-10 sm:px-6'><h1 className='text-3xl font-extrabold'>Standings</h1><p className='mb-7 mt-2 text-slate-600'>Division records and rankings calculated from published scores.</p><PublicResults view='standings' /></main></PublicLayout>; }
