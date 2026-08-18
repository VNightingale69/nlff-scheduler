'use client';

import { useEffect, useMemo, useState } from 'react';
import { API_URL } from '@/lib/api';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';
import { fieldTypeLabel, getDivisionScoringInfo } from '@/lib/divisionScoring';
import StandingsTable from '@/components/StandingsTable';
import TeamWithLogo from '@/components/TeamWithLogo';
import TouchdownGuide from './TouchdownGuide';

type Standing = { rank: number; team_id?: string; team_name: string; organization_name?: string; community_name?: string; community_logo_url?: string | null; community_logo_alt_text?: string | null; wins: number; losses: number; ties: number };
type Division = { division: { id: string; name: string; division_group?: string }; standings: Standing[] };
type Game = { game_id: string; date: string; time?: string | null; division_id: string; division_name: string; division_group?: string; field_type?: string | null; host_location?: string | null; field?: string | null; home_team: string; home_organization_id?: string; home_organization_name?: string; home_organization_logo_url?: string | null; home_organization_logo_alt_text?: string | null; away_team: string; away_organization_id?: string; away_organization_name?: string; away_organization_logo_url?: string | null; away_organization_logo_alt_text?: string | null; home_score: number | string | null; away_score: number | string | null; is_official: boolean };
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
      {view === 'scores' && <p className='text-sm text-slate-600'>{payload.official_score_note || 'Published scores only.'}</p>}
      <label className='text-sm font-semibold text-slate-700'>Division <select aria-label='Division' className='ml-2 rounded-md border bg-white px-3 py-2 font-normal' value={division} onChange={event => setDivision(event.target.value)}><option value=''>All divisions</option>{divisions.map(item => <option key={item.division.id} value={item.division.id}>{item.division.division_group ? `${item.division.division_group} ` : ''}{item.division.name}</option>)}</select></label>
    </div>
    {view === 'standings' ? <div className='grid items-start gap-5 xl:grid-cols-2'>{visibleDivisions.map(block => <section key={block.division.id} className='w-full max-w-[760px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm'>
      <div className='flex items-center justify-between gap-3 bg-slate-100 px-4 py-3 sm:px-5'><h2 className='text-lg font-bold'>{block.division.division_group} {block.division.name}</h2><span className='text-sm font-medium text-slate-500'>{block.standings.length} {block.standings.length === 1 ? 'Team' : 'Teams'}</span></div>
      <StandingsTable rows={block.standings} divisionId={block.division.id} />
    </section>)}{visibleDivisions.length === 0 && <p className='rounded-lg border bg-white p-5'>No published standings are available.</p>}</div>
    : <div data-testid='scores-guide-layout' className='grid items-start gap-5 min-[900px]:grid-cols-[minmax(0,3fr)_minmax(250px,1fr)] min-[900px]:gap-6'>
      <div className='order-2 space-y-3 min-[900px]:order-1' aria-live='polite'>
        {officialGames.map(game => { const scoring = getDivisionScoringInfo(game.division_group, game.division_name, game.field_type); return <article key={game.game_id} className='overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm'>
          <div className='flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 bg-slate-50 px-4 py-3 sm:px-5'>
            <div className='flex flex-wrap items-center gap-2'>{scoring && <span className='rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-extrabold uppercase tracking-wide text-emerald-900'>{fieldTypeLabel(scoring.fieldType)}</span>}<h2 className='font-bold text-slate-900'>{game.division_group} {game.division_name}</h2></div>
            <span className='rounded-full bg-slate-900 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-white'>Final</span>
          </div>
          <div className='grid gap-5 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(220px,0.7fr)] sm:p-5'>
            <div className='space-y-4'>
              <div className='grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3'><TeamWithLogo teamName={game.home_team} organizationName={game.home_organization_name} logoUrl={game.home_organization_logo_url} logoAltText={game.home_organization_logo_alt_text} logoSize={36} className='font-semibold' /><div className='text-right'><span className='block text-2xl font-extrabold'>{game.home_score}</span><span className='text-[10px] font-bold uppercase tracking-wide text-slate-500'>Home</span></div></div>
              <div className='grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3'><TeamWithLogo teamName={game.away_team} organizationName={game.away_organization_name} logoUrl={game.away_organization_logo_url} logoAltText={game.away_organization_logo_alt_text} logoSize={36} className='font-semibold' /><div className='text-right'><span className='block text-2xl font-extrabold'>{game.away_score}</span><span className='text-[10px] font-bold uppercase tracking-wide text-slate-500'>Away</span></div></div>
            </div>
            <dl className='grid grid-cols-2 content-center gap-x-4 gap-y-3 border-t border-slate-100 pt-4 text-sm sm:block sm:space-y-3 sm:border-l sm:border-t-0 sm:pl-5 sm:pt-0'>
              <div><dt className='text-xs font-bold uppercase tracking-wide text-slate-500'>Date &amp; kickoff</dt><dd className='mt-0.5 font-medium'>{formatDisplayDate(game.date)}{game.time ? ` · ${formatDisplayTime(game.time)}` : ''}</dd></div>
              <div><dt className='text-xs font-bold uppercase tracking-wide text-slate-500'>Host location</dt><dd className='mt-0.5 font-medium'>{game.host_location || 'Location not listed'}</dd></div>
              <div><dt className='text-xs font-bold uppercase tracking-wide text-slate-500'>Field</dt><dd className='mt-0.5 font-medium'>{game.field || 'Field not listed'}</dd></div>
            </dl>
          </div>
        </article>; })}
        {officialGames.length === 0 && <p className='rounded-xl border border-slate-200 bg-white p-6 text-center text-slate-600 shadow-sm'>No published scores are available.</p>}
      </div>
      <div data-testid='scores-guide-sidebar' className='order-1 min-[900px]:sticky min-[900px]:top-20 min-[900px]:order-2 min-[900px]:self-start'><TouchdownGuide /></div>
    </div>}
  </>;
}
