import type { Metadata } from 'next';
import PublicLayout from '@/components/public/PublicLayout';
import PublicResults from '@/components/public/PublicResults';

export const metadata: Metadata = { title: 'Scores | Community Flag Football' };
export default function ScoresPage() { return <PublicLayout><main className='mx-auto w-full max-w-[1500px] px-4 py-8 sm:px-6 sm:py-10 lg:px-8'><h1 className='text-3xl font-extrabold'>Scores</h1><p className='mt-2 text-slate-600'>See final scores from this season&apos;s flag football games.</p><div className='mt-7'><PublicResults view='scores' /></div></main></PublicLayout>; }
