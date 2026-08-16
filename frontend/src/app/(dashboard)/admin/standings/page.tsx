'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { canManageSchedule } from '@/lib/auth';
import { useAuthSession } from '@/components/AuthGate';
import StandingsTable from '@/components/StandingsTable';

type StandingRow = {
  rank: number;
  team_id: string;
  team_name: string;
  community_id: string;
  community_name: string;
  organization_id?: string;
  organization_name?: string;
  community_logo_url?: string | null;
  community_logo_alt_text?: string | null;
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

export default function StandingsPage() {
  const { accessToken, currentUser } = useAuthSession();
  const token = accessToken || undefined;
  const [payload, setPayload] = useState<{ season_id?: string; divisions: DivisionBlock[]; game_results: GameResult[]; last_calculated_at: string; official_score_note: string; total_missing_or_not_played: number; no_active_season?: boolean } | null>(null);
  const [message, setMessage] = useState('');
  const canBuildTournament = canManageSchedule(currentUser);

  const load = async () => {
    try {
      setPayload(await apiFetch('/standings', {}, token));
      setMessage('');
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load standings.');
    }
  };

  useEffect(() => { load(); }, []);

  return <div className='space-y-5'>
    <div>
      <h1 className='text-2xl font-bold'>Results & Standings</h1>
      {canBuildTournament && payload?.season_id && <Link className='mt-3 inline-flex rounded bg-slate-800 px-3 py-2 text-sm text-white' href={`/admin/tournaments?season_id=${payload.season_id}`}>Create Tournament from Standings</Link>}
    </div>

    {message && <div className='rounded border bg-red-50 p-3 text-sm text-red-700'>{message}</div>}
    {payload?.no_active_season && <div className='rounded border bg-amber-50 p-3 text-sm text-amber-800'>No active season selected.</div>}

    {(payload?.divisions || []).map((division) => <section key={division.division.id} className='space-y-3 rounded border bg-white p-4'>
      <h2 className='text-xl font-semibold'>{division.division.division_group} {division.division.name}</h2>
      <StandingsTable rows={division.standings} divisionId={division.division.id} />
    </section>)}
  </div>;
}
