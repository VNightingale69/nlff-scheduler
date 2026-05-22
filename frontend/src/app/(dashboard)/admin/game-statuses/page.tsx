'use client';
import { useEffect, useState } from 'react';
import { apiFetch, ApiError } from '@/lib/api';
import { getToken } from '@/lib/auth';

export default function GameStatusesPage() {
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch('/game-statuses?page=1&page_size=100', {}, getToken());
      setItems(data.items || []);
    } catch (err) {
      console.error('[GameStatusesPage] Failed to load game statuses', err);
      setError('Could not load game statuses right now. Please try again.');
    } finally { setLoading(false); }
  };

  const ensureRequired = async () => {
    try {
      await apiFetch('/game-statuses/seed', { method: 'POST' }, getToken());
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to seed required game statuses.');
      console.error('[GameStatusesPage] Failed to seed game statuses', err);
    }
  };

  useEffect(() => { void load(); }, []);
  return <div className='space-y-4'><div className='flex items-center justify-between'><h1 className='text-2xl font-bold'>Game Statuses</h1><button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={ensureRequired}>Ensure Required Statuses</button></div><p className='text-sm text-slate-600'>Required: SCHEDULED, COMPLETED, CANCELLED, POSTPONED, FORFEIT.</p>{error && <div className='rounded border border-red-300 bg-red-50 p-3 text-red-700'>{error}</div>}{loading ? <p>Loading...</p> : <div className='overflow-x-auto rounded border'><table className='w-full text-sm'><thead><tr><th className='p-2 text-left'>Code</th><th className='p-2 text-left'>Label</th></tr></thead><tbody>{items.map((x: any) => <tr key={x.id} className='border-t'><td className='p-2 font-mono'>{x.code}</td><td className='p-2'>{x.label}</td></tr>)}</tbody></table></div>}</div>;
}
