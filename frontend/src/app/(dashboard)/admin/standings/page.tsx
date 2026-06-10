'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

type StandingRow = {
  rank: number;
  team_name: string;
  community_name: string;
  division_name: string;
  wins: number;
  losses: number;
  ties: number;
  games_played: number;
  games_scheduled: number;
  games_remaining: number;
};

type DivisionBlock = {
  division: { id: string; name: string; division_group: string };
  summary: Record<string, number>;
  standings: StandingRow[];
  message?: string | null;
};

type GameResult = {
  game_id: string;
  date: string;
  time: string;
  division_name: string;
  division_group: string;
  home_team: string;
  away_team: string;
  home_score: number | string | null;
  away_score: number | string | null;
  winner: string | null;
  score_status: string;
  published_status: string;
  result_status: string;
  actions: string[];
};

const standingsHeaders = ['Rank', 'Team', 'Community', 'Division', 'W', 'L', 'T', 'GP', 'Scheduled', 'Remaining'];

function scoreText(value: number | string | null) {
  return value === null || value === undefined ? '—' : String(value);
}

export default function StandingsPage() {
  const token = getToken() || undefined;
  const [payload, setPayload] = useState<{ divisions: DivisionBlock[]; game_results: GameResult[]; last_calculated_at: string; official_score_note: string; total_missing_or_not_played: number; no_active_season?: boolean } | null>(null);
  const [message, setMessage] = useState('');

  const load = async () => {
    try {
      setPayload(await apiFetch('/standings', {}, token));
      setMessage('');
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load standings.');
    }
  };

  useEffect(() => { load(); }, []);

  const missing = payload?.total_missing_or_not_played || 0;

  return <div className='space-y-5'>
    <div>
      <h1 className='text-2xl font-bold'>Results & Standings</h1>
      <p className='text-sm text-slate-600'>Division rankings, missing game counts, and result summaries based on the official score workflow.</p>
      <p className='text-xs font-semibold text-slate-500'>Standings calculated from published scores only.</p>
    </div>

    {message && <div className='rounded border bg-red-50 p-3 text-sm text-red-700'>{message}</div>}
    {payload && <div className='rounded border bg-blue-50 p-3 text-sm text-blue-900'>
      <div>{payload.official_score_note}</div>
      <div>Calculated at: {payload.last_calculated_at || '—'}</div>
      {missing > 0 && <div className='font-semibold'>Standings may be incomplete because {missing} games are missing scores, pending approval, unpublished, flagged/conflicted, correction pending, or future games.</div>}
    </div>}

    {payload?.no_active_season && <div className='rounded border bg-amber-50 p-3 text-sm text-amber-800'>No active season selected.</div>}

    {(payload?.divisions || []).map((division) => <section key={division.division.id} className='space-y-3 rounded border bg-white p-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div><h2 className='text-xl font-semibold'>{division.division.division_group} {division.division.name}</h2>{division.message && <p className='text-sm text-slate-500'>{division.message}</p>}</div>
        <div className='grid grid-cols-2 gap-2 text-xs md:grid-cols-6'>
          <div className='rounded bg-slate-100 p-2'>Scheduled: <strong>{division.summary.scheduled || 0}</strong></div>
          <div className='rounded bg-green-100 p-2'>Official/Played: <strong>{division.summary.official_played || 0}</strong></div>
          <div className='rounded bg-amber-100 p-2'>Missing: <strong>{division.summary.missing || 0}</strong></div>
          <div className='rounded bg-yellow-100 p-2'>Pending: <strong>{division.summary.pending_approval || 0}</strong></div>
          <div className='rounded bg-red-100 p-2'>Flagged/Conflict: <strong>{division.summary.flagged_conflict || 0}</strong></div>
          <div className='rounded bg-slate-100 p-2'>Future: <strong>{division.summary.future || 0}</strong></div>
        </div>
      </div>
      <div className='overflow-x-auto'>
        <table className='min-w-full text-sm'>
          <thead className='bg-slate-100 text-left'>
            <tr>{standingsHeaders.map((h) => <th key={h} className='p-2'>{h}</th>)}</tr>
          </thead>
          <tbody>{division.standings.map((row) => <tr key={row.team_name} className='border-t'>
            <td className='p-2'>{row.rank}</td>
            <td className='p-2 font-medium'>{row.team_name}</td>
            <td className='p-2'>{row.community_name}</td>
            <td className='p-2'>{row.division_name}</td>
            <td className='p-2'>{row.wins}</td>
            <td className='p-2'>{row.losses}</td>
            <td className='p-2'>{row.ties}</td>
            <td className='p-2'>{row.games_played}</td>
            <td className='p-2'>{row.games_scheduled}</td>
            <td className='p-2'>{row.games_remaining}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>)}

    <section className='space-y-3 rounded border bg-white p-4'>
      <h2 className='text-xl font-semibold'>Game Results & Missing Scores</h2>
      <div className='overflow-x-auto'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Date','Time','Division','Home Team','Away Team','Home Score','Away Score','Winner','Score Status','Published Status','Result Status','Actions'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{(payload?.game_results || []).map((game) => <tr key={game.game_id} className='border-t'><td className='p-2'>{formatDisplayDate(game.date)}</td><td className='p-2'>{formatDisplayTime(game.time)}</td><td className='p-2'>{game.division_group} {game.division_name}</td><td className='p-2'>{game.home_team}</td><td className='p-2'>{game.away_team}</td><td className='p-2'>{scoreText(game.home_score)}</td><td className='p-2'>{scoreText(game.away_score)}</td><td className='p-2'>{game.winner || '—'}</td><td className='p-2'>{game.score_status}</td><td className='p-2'>{game.published_status}</td><td className='p-2'>{game.result_status}</td><td className='p-2'>{game.actions.includes('View in Score Management') ? <Link className='rounded border px-2 py-1' href='/admin/scores'>View in Score Management</Link> : game.actions.join(', ')}</td></tr>)}</tbody></table></div>
    </section>
  </div>;
}
