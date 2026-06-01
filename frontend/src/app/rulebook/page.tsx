'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { API_URL } from '@/lib/api';
import { APP_NAME } from '@/config/branding';

type Rulebook = {
  original_filename: string;
  file_size_bytes: number;
  uploaded_at: string;
  uploaded_by_name?: string | null;
  uploaded_by_email?: string | null;
  view_url: string;
  download_url: string;
};

const formatBytes = (bytes: number) => {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

export default function PublicRulebookPage() {
  const [rulebook, setRulebook] = useState<Rulebook | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setMessage('');
      const response = await fetch(`${API_URL}/public/rulebook`);
      if (response.status === 404) {
        setRulebook(null);
        setMessage('No rulebook has been uploaded yet.');
      } else if (response.ok) {
        setRulebook(await response.json());
      } else {
        setMessage('Unable to load the rulebook. Please try again later.');
      }
      setLoading(false);
    };
    load();
  }, []);

  return (
    <main className='mx-auto max-w-4xl space-y-4 p-4'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div>
          <h1 className='text-2xl font-bold'>Rulebook</h1>
          <p className='mt-1 text-sm text-slate-600'>{APP_NAME}</p>
        </div>
        <Link className='rounded border px-3 py-2 text-sm hover:bg-slate-50' href='/schedule'>Published Schedule</Link>
      </div>

      {loading && <div className='rounded border p-4'>Loading rulebook...</div>}
      {!loading && message && <div className='rounded border p-4'>{message}</div>}
      {!loading && rulebook && (
        <section className='rounded border bg-white p-4 shadow-sm'>
          <h2 className='text-lg font-semibold'>{rulebook.original_filename}</h2>
          <dl className='mt-3 grid gap-2 text-sm sm:grid-cols-2'>
            <div><dt className='font-medium text-slate-500'>Uploaded</dt><dd>{new Date(rulebook.uploaded_at).toLocaleString()}</dd></div>
            <div><dt className='font-medium text-slate-500'>File size</dt><dd>{formatBytes(rulebook.file_size_bytes)}</dd></div>
          </dl>
          <div className='mt-4 flex flex-wrap gap-2'>
            <a className='rounded bg-slate-800 px-3 py-2 text-white' href={`${API_URL}/public/rulebook/view`} target='_blank' rel='noreferrer'>View</a>
            <a className='rounded border px-3 py-2' href={`${API_URL}/public/rulebook/download`}>Download</a>
          </div>
        </section>
      )}
    </main>
  );
}
