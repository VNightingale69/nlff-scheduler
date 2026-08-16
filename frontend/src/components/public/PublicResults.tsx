'use client';

import { useEffect, useMemo, useState } from 'react';
import { API_URL } from '@/lib/api';
import { formatDisplayDate } from '@/lib/displayFormat';

type Standing = { rank: number; team_name: string; organization_name?: string; wins: number; losses: number; ties: number };
type Division = { division: { id: string; name: string; division_group?: string }; standings: Standing[] };
type Game = { game_id: string; date: string; division_id: string; division_name: string; division_group?: string; home_team: string; away_team: string; home_score: number | string | null; away_score: number | string | null; is_official: boolean };
type Payload = { divisions: Division[]; game_results: Game[]; official_score_note?: string };

export default function PublicResults({ view }: { view: 'standings' | 'scores' }) {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [error, setError] = useState('');
  const [division, setDivision] = useState('');
  useEffect(() => { fetch(`${API_URL}/public/standings`).then(async response => {
    if (!response.ok) throw new Error('Unable to load published results.');
    setPayload(await response.json());
  }).catch(reason => setError(reason.message)); }, []);
  const divisions = payload?.divisions || [];
  const visibleDivisions = division ? divisions.filter(item => item.division.id === division) : divisions;
  const officialGames = useMemo(() => (payload?.game_results || []).filter(game => game.is_official && (!division || game.division_id === division)), [payload, division]);

  if (error) return <div role='alert' className='rounded-lg border border-red-200 bg-red-50 p-4 text-red-800'>{error}</div>;
  if (!payload) return <div className='rounded-lg border bg-white p-4'>Loading published {view}…</div>;
  return <>
    <div className='mb-6 flex flex-wrap items-center justify-between gap-3'>
      <p className='text-sm text-slate-600'>{payload.official_score_note || 'Published scores only.'}</p>
      <label className='text-sm font-semibold text-slate-700'>Division <select aria-label='Division' className='ml-2 rounded-md border bg-white px-3 py-2 font-normal' value={division} onChange={event => setDivision(event.target.value)}><option value=''>All divisions</option>{divisions.map(item => <option key={item.division.id} value={item.division.id}>{item.division.division_group ? `${item.division.division_group} ` : ''}{item.division.name}</option>)}</select></label>
    </div>
    {view === 'standings' ? <div className='space-y-7'>{visibleDivisions.map(block => <section key={block.division.id} className='overflow-hidden rounded-xl border bg-white shadow-sm'>
      <h2 className='bg-slate-100 px-4 py-3 text-lg font-bold'>{block.division.division_group} {block.division.name}</h2>
      <div className='overflow-x-auto'><table className='w-full min-w-[540px] text-sm'><thead><tr className='border-b text-left text-slate-600'><th className='p-3'>Rank</th><th className='p-3'>Team</th><th className='p-3'>W</th><th className='p-3'>L</th><th className='p-3'>T</th><th className='p-3'>Record</th></tr></thead><tbody>{block.standings.map(row => <tr key={`${block.division.id}-${row.team_name}`} className='border-b last:border-0'><td className='p-3 font-bold'>{row.rank}</td><td className='p-3'><span className='font-semibold'>{row.team_name}</span>{row.organization_name && <span className='block text-xs text-slate-500'>{row.organization_name}</span>}</td><td className='p-3'>{row.wins}</td><td className='p-3'>{row.losses}</td><td className='p-3'>{row.ties}</td><td className='p-3 font-medium'>{row.wins}-{row.losses}{row.ties ? `-${row.ties}` : ''}</td></tr>)}</tbody></table></div>
    </section>)}{visibleDivisions.length === 0 && <p className='rounded-lg border bg-white p-5'>No published standings are available.</p>}</div>
    : <div className='overflow-x-auto rounded-xl border bg-white shadow-sm'><table className='w-full min-w-[720px] text-sm'><thead className='bg-slate-100'><tr className='text-left'><th className='p-3'>Date</th><th className='p-3'>Division</th><th className='p-3'>Home Team</th><th className='p-3 text-center'>Score</th><th className='p-3'>Away Team</th><th className='p-3 text-center'>Score</th></tr></thead><tbody>{officialGames.map(game => <tr key={game.game_id} className='border-t'><td className='whitespace-nowrap p-3'>{formatDisplayDate(game.date)}</td><td className='p-3'>{game.division_group} {game.division_name}</td><td className='p-3 font-medium'>{game.home_team}</td><td className='p-3 text-center text-lg font-bold'>{game.home_score}</td><td className='p-3 font-medium'>{game.away_team}</td><td className='p-3 text-center text-lg font-bold'>{game.away_score}</td></tr>)}{officialGames.length === 0 && <tr><td colSpan={6} className='p-6 text-center text-slate-600'>No published scores are available.</td></tr>}</tbody></table></div>}
  </>;
}
