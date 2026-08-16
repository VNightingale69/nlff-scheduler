import type { Metadata } from 'next';
import PublicLayout from '@/components/public/PublicLayout';
import PublicResults from '@/components/public/PublicResults';

export const metadata: Metadata = { title: 'Standings | Community Flag Football' };
export default function StandingsPage() { return <PublicLayout><main className='mx-auto w-full max-w-[1500px] px-4 py-8 sm:px-6 sm:py-10 lg:px-8'><h1 className='mb-7 text-3xl font-extrabold'>Standings</h1><PublicResults view='standings' /></main></PublicLayout>; }
