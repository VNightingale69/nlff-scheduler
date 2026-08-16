import type { Metadata } from 'next';
import PublicLayout from '@/components/public/PublicLayout';
import PublicResults from '@/components/public/PublicResults';

export const metadata: Metadata = { title: 'Scores | Community Flag Football' };
export default function ScoresPage() { return <PublicLayout><main className='mx-auto max-w-6xl px-4 py-10 sm:px-6'><h1 className='text-3xl font-extrabold'>Scores</h1><p className='mb-7 mt-2 text-slate-600'>Completed games with approved, published scores.</p><PublicResults view='scores' /></main></PublicLayout>; }
