'use client';

import { useEffect, useMemo, useState } from 'react';
import { API_URL } from '@/lib/api';
import { formatDisplayDate } from '@/lib/displayFormat';
import CommunityLogo from '@/components/CommunityLogo';

type Standing = { rank: number; team_id?: string; team_name: string; organization_name?: string; community_name?: string; community_logo_url?: string | null; community_logo_alt_text?: string | null; wins: number; losses: number; ties: number };
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
      <div className='flex items-center justify-between gap-3 bg-slate-100 px-4 py-3 sm:px-5'><h2 className='text-lg font-bold'>{block.division.division_group} {block.division.name}</h2><span className='text-sm font-medium text-slate-500'>{block.standings.length} {block.standings.length === 1 ? 'Team' : 'Teams'}</span></div>
      <div className='overflow-x-auto'><table className='w-full min-w-[650px] table-fixed text-sm'><colgroup><col className='w-[70px]' /><col /><col className='w-[72px] sm:w-[90px]' /><col className='w-[72px] sm:w-[90px]' /><col className='w-[72px] sm:w-[90px]' /><col className='w-[100px] sm:w-[120px]' /></colgroup><thead><tr className='border-b text-left text-slate-600'><th className='px-3 py-3 sm:px-4'>Rank</th><th className='px-3 py-3 sm:px-4'>Team</th><th className='px-3 py-3 text-center sm:px-4'>W</th><th className='px-3 py-3 text-center sm:px-4'>L</th><th className='px-3 py-3 text-center sm:px-4'>T</th><th className='px-3 py-3 text-center sm:px-4'>Record</th></tr></thead><tbody>{block.standings.map(row => {
        const communityName = row.organization_name || row.community_name || 'Community';
        return <tr key={row.team_id || `${block.division.id}-${row.team_name}`} className='border-b transition-colors last:border-0 hover:bg-slate-50'><td className='px-3 py-3 font-bold sm:px-4'>{row.rank}</td><td className='px-3 py-3 sm:px-4'><div className='flex min-w-0 items-center gap-2.5 sm:gap-3'><CommunityLogo src={row.community_logo_url} name={communityName} altText={row.community_logo_alt_text} size={40} className='h-8 w-8 p-1 sm:h-10 sm:w-10' /><div className='min-w-0'><div className='font-semibold text-slate-900'>{row.team_name}</div><div className='text-xs text-slate-500 sm:text-sm'>{communityName}</div></div></div></td><td className='px-3 py-3 text-center sm:px-4'>{row.wins}</td><td className='px-3 py-3 text-center sm:px-4'>{row.losses}</td><td className='px-3 py-3 text-center sm:px-4'>{row.ties}</td><td className='px-3 py-3 text-center font-medium sm:px-4'>{row.wins}-{row.losses}{row.ties ? `-${row.ties}` : ''}</td></tr>;
      })}</tbody></table></div>
    </section>)}{visibleDivisions.length === 0 && <p className='rounded-lg border bg-white p-5'>No published standings are available.</p>}</div>
    : <div className='overflow-x-auto rounded-xl border bg-white shadow-sm'><table className='w-full min-w-[720px] text-sm'><thead className='bg-slate-100'><tr className='text-left'><th className='p-3'>Date</th><th className='p-3'>Division</th><th className='p-3'>Home Team</th><th className='p-3 text-center'>Score</th><th className='p-3'>Away Team</th><th className='p-3 text-center'>Score</th></tr></thead><tbody>{officialGames.map(game => <tr key={game.game_id} className='border-t'><td className='whitespace-nowrap p-3'>{formatDisplayDate(game.date)}</td><td className='p-3'>{game.division_group} {game.division_name}</td><td className='p-3 font-medium'>{game.home_team}</td><td className='p-3 text-center text-lg font-bold'>{game.home_score}</td><td className='p-3 font-medium'>{game.away_team}</td><td className='p-3 text-center text-lg font-bold'>{game.away_score}</td></tr>)}{officialGames.length === 0 && <tr><td colSpan={6} className='p-6 text-center text-slate-600'>No published scores are available.</td></tr>}</tbody></table></div>}
  </>;
}
