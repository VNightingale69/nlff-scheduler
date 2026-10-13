'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api';
import TournamentBracket, { type TournamentBracketDivision } from '@/components/TournamentBracket';
import { tournamentViews, type TournamentView } from '@/lib/tournamentViews';
import { APP_SCHEDULE_NAME } from '@/config/branding';

type PublicTournament = {
  id: string;
  name: string;
  season_id?: string;
  type?: string;
  status: string;
  is_published?: boolean;
  bracket_is_published?: boolean;
  published_at?: string | null;
  divisions: TournamentBracketDivision[];
};

export default function PublicTournamentsPage() {
  const [views, setViews] = useState<TournamentView<PublicTournament>[]>([]);
  const [selectedTournamentId, setSelectedTournamentId] = useState('');
  const [brackets, setBrackets] = useState<PublicTournament[]>([]);
  const requestVersion = useRef(0);
  const selectedView = views.find(view => view.id === selectedTournamentId);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  const loadList = async () => {
    setLoading(true);
    try {
      const payload = await apiFetch('/public/tournaments');
      const only = new URLSearchParams(window.location.search).get('bracketOnly') === '1';
      const items = (payload.items || []).filter((item: PublicTournament) => !only || item.bracket_is_published);
      const grouped = tournamentViews<PublicTournament>(items);
      setViews(grouped);
      const requestedId = new URLSearchParams(window.location.search).get('tournament');
      const nextView = grouped.find(view => view.id === selectedTournamentId) || grouped.find(view => view.id === requestedId || view.tournaments.some(t => t.id === requestedId)) || grouped[0];
      const nextId = nextView?.id || '';
      setSelectedTournamentId(nextId);
      if (nextView) await loadBracket(nextView);
      else setBrackets([]);
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load published tournaments.');
    } finally {
      setLoading(false);
    }
  };

  const loadBracket = async (view: TournamentView<PublicTournament>) => {
    const version = ++requestVersion.current;
    const only = new URLSearchParams(window.location.search).get('bracketOnly') === '1';
    const results = await Promise.all(view.tournaments.map(async tournament => {
      const payload = await apiFetch(`/public/tournaments/${tournament.id}/${only ? 'bracket-only' : 'bracket'}`);
      return payload.tournament as PublicTournament;
    }));
    if (version === requestVersion.current) setBrackets(results);
  };

  useEffect(() => { loadList(); }, []);

  const onSelectTournament = async (id: string) => {
    const view = views.find(item => item.id === id);
    if (!view) return;
    setSelectedTournamentId(id);
    setBrackets([]);
    setMessage('');
    setLoading(true);
    const version = requestVersion.current + 1;
    try {
      await loadBracket(view);
    } catch (error: any) {
      if (version === requestVersion.current) setMessage(error?.message || 'Unable to load the published brackets.');
    } finally {
      if (version === requestVersion.current) setLoading(false);
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
            {views.length === 0 && <option value=''>No published tournaments</option>}
            {views.map(view => <option key={view.id} value={view.id}>{view.name}</option>)}
          </select>
        </label>
      </section>

      {loading && <div className='rounded border p-4'>Loading published bracket...</div>}
      {!loading && brackets.length === 0 && <div className='rounded border p-4 text-sm text-slate-600'>No published tournament bracket is available.</div>}
      {!loading && brackets.length > 0 && (
        <section className='space-y-4 rounded border bg-white p-4'>
          <div>
            <h2 className='text-xl font-semibold'>{selectedView?.name}</h2>
            <p className='text-sm text-slate-600'>Published bracket · unpublished score workflow details are hidden.</p>
          </div>
          <div className='flex flex-wrap gap-2 text-sm'>
            {brackets.flatMap(bracket => bracket.divisions).map((division) => <a key={division.id} className='rounded border px-2 py-1 hover:bg-slate-50' href={`#division-${division.id}`}>{division.division_group} {division.division_name}</a>)}
          </div>
          {brackets.map(bracket => <div key={bracket.id} className='space-y-3'>
            {brackets.length > 1 && <h3 className='text-lg font-semibold'>{bracket.name}</h3>}
            <TournamentBracket divisions={bracket.divisions} publicView tournamentId={bracket.id} tournamentTitle={selectedView?.name || bracket.name} />
          </div>)}
        </section>
      )}
    </main>
  );
}
