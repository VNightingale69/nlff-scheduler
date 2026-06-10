'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api';
import TournamentBracket, { type TournamentBracketDivision } from '@/components/TournamentBracket';
import { APP_SCHEDULE_NAME } from '@/config/branding';

type PublicTournament = {
  id: string;
  name: string;
  status: string;
  is_published: boolean;
  published_at?: string | null;
  divisions: TournamentBracketDivision[];
};

export default function PublicTournamentsPage() {
  const [tournaments, setTournaments] = useState<PublicTournament[]>([]);
  const [selectedTournamentId, setSelectedTournamentId] = useState('');
  const [bracket, setBracket] = useState<PublicTournament | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  const loadList = async () => {
    setLoading(true);
    try {
      const payload = await apiFetch('/public/tournaments');
      const items = payload.items || [];
      setTournaments(items);
      const nextId = selectedTournamentId || items[0]?.id || '';
      setSelectedTournamentId(nextId);
      if (nextId) await loadBracket(nextId);
      else setBracket(null);
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load published tournaments.');
    } finally {
      setLoading(false);
    }
  };

  const loadBracket = async (id: string) => {
    const payload = await apiFetch(`/public/tournaments/${id}/bracket`);
    setBracket(payload.tournament);
  };

  useEffect(() => { loadList(); }, []);

  const onSelectTournament = async (id: string) => {
    setSelectedTournamentId(id);
    setLoading(true);
    try {
      await loadBracket(id);
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load the published bracket.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className='mx-auto max-w-7xl space-y-5 p-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div>
          <h1 className='text-2xl font-bold'>Published Tournament Bracket</h1>
          <p className='mt-1 text-sm text-slate-600'>{APP_SCHEDULE_NAME} tournament results and advancement paths.</p>
        </div>
        <Link className='rounded border px-3 py-2 text-sm hover:bg-slate-50' href='/schedule'>Schedule View</Link>
      </div>

      {message && <div className='rounded border bg-amber-50 p-3 text-sm text-amber-900'>{message}</div>}

      <section className='rounded border bg-white p-4'>
        <label className='text-sm font-medium'>Tournament
          <select className='mt-1 w-full rounded border p-2 md:max-w-md' value={selectedTournamentId} onChange={(e) => onSelectTournament(e.target.value)}>
            {tournaments.length === 0 && <option value=''>No published tournaments</option>}
            {tournaments.map((tournament) => <option key={tournament.id} value={tournament.id}>{tournament.name}</option>)}
          </select>
        </label>
      </section>

      {loading && <div className='rounded border p-4'>Loading published bracket...</div>}
      {!loading && !bracket && <div className='rounded border p-4 text-sm text-slate-600'>No published tournament bracket is available.</div>}
      {!loading && bracket && (
        <section className='space-y-4 rounded border bg-white p-4'>
          <div>
            <h2 className='text-xl font-semibold'>{bracket.name}</h2>
            <p className='text-sm text-slate-600'>Published bracket · unpublished score workflow details are hidden.</p>
          </div>
          <div className='flex flex-wrap gap-2 text-sm'>
            {bracket.divisions.map((division) => <a key={division.id} className='rounded border px-2 py-1 hover:bg-slate-50' href={`#division-${division.id}`}>{division.division_group} {division.division_name}</a>)}
          </div>
          <TournamentBracket divisions={bracket.divisions} publicView tournamentTitle={bracket.name} />
        </section>
      )}
    </main>
  );
}
