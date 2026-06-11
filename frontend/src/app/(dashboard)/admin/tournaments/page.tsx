'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';
import TournamentBracket, { type TournamentBracketGame } from '@/components/TournamentBracket';

type SeedTeam = { team_id: string; team_name: string; community_name: string; seed: number; included: boolean; original_standings_rank?: number | null; seed_source: string };
type Division = { id: string; name: string; division_group: string; sort_order?: number };
type Season = { id: string; name: string; is_active: boolean };
type TournamentGame = TournamentBracketGame;
type Tournament = { id: string; name: string; status: string; is_published: boolean; divisions: { id: string; division_name: string; division_group: string; teams: SeedTeam[]; games: TournamentGame[] }[] };

const divisionLabel = (division: Division) => `${division.division_group} ${division.name}`;

export default function TournamentBuilderPage() {
  const { accessToken } = useAuthSession();
  const token = accessToken || undefined;
  const searchParams = useSearchParams();
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [seasonId, setSeasonId] = useState('');
  const [selectedDivisions, setSelectedDivisions] = useState<string[]>([]);
  const [name, setName] = useState('');
  const [seedRows, setSeedRows] = useState<Record<string, SeedTeam[]>>({});
  const [warnings, setWarnings] = useState<Record<string, string>>({});
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [viewModes, setViewModes] = useState<Record<string, 'schedule' | 'bracket'>>({});

  const selectedDivisionObjects = useMemo(() => divisions.filter((division) => selectedDivisions.includes(division.id)), [divisions, selectedDivisions]);

  const loadOptions = async () => {
    try {
      const [seasonPayload, divisionPayload, tournamentPayload] = await Promise.all([
        apiFetch('/seasons', {}, token),
        apiFetch('/standings/divisions', {}, token),
        apiFetch('/tournaments', {}, token),
      ]);
      const seasonItems = seasonPayload.items || seasonPayload || [];
      setSeasons(seasonItems);
      setSeasonId((current) => current || searchParams.get('season_id') || seasonItems.find((s: Season) => s.is_active)?.id || seasonItems[0]?.id || '');
      setDivisions(divisionPayload.items || []);
      setTournaments(tournamentPayload.items || []);
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load Tournament Builder data.');
    }
  };

  useEffect(() => { loadOptions(); }, []);

  useEffect(() => {
    const timer = window.setInterval(() => { loadOptions(); }, 30000);
    return () => window.clearInterval(timer);
  }, [token]);

  const toggleDivision = (divisionId: string) => {
    setSelectedDivisions((current) => current.includes(divisionId) ? current.filter((id) => id !== divisionId) : [...current, divisionId]);
  };

  const loadSeeds = async () => {
    if (!seasonId || selectedDivisions.length === 0) {
      setMessage('Select a season and at least one division before loading seeds.');
      return;
    }
    setLoading(true);
    try {
      const nextRows: Record<string, SeedTeam[]> = {};
      const nextWarnings: Record<string, string> = {};
      for (const divisionId of selectedDivisions) {
        const payload = await apiFetch(`/tournaments/seed-preview?season_id=${seasonId}&division_id=${divisionId}`, {}, token);
        nextRows[divisionId] = payload.teams || [];
        if (payload.warning) nextWarnings[divisionId] = payload.warning;
      }
      setSeedRows(nextRows);
      setWarnings(nextWarnings);
      setMessage('Seeds loaded from Results & Standings. Adjust seeds or exclusions before generating the bracket.');
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load seeds.');
    } finally {
      setLoading(false);
    }
  };

  const updateSeed = (divisionId: string, teamId: string, seed: number) => {
    setSeedRows((current) => ({ ...current, [divisionId]: (current[divisionId] || []).map((row) => row.team_id === teamId ? { ...row, seed, seed_source: 'MANUAL' } : row).sort((a, b) => a.seed - b.seed) }));
  };

  const toggleTeam = (divisionId: string, teamId: string) => {
    setSeedRows((current) => ({ ...current, [divisionId]: (current[divisionId] || []).map((row) => row.team_id === teamId ? { ...row, included: !row.included, seed_source: 'MANUAL' } : row) }));
  };

  const createTournament = async () => {
    if (!seasonId || selectedDivisions.length === 0) return setMessage('Select a season and at least one division.');
    setLoading(true);
    try {
      const allRows = selectedDivisions.flatMap((divisionId) => seedRows[divisionId] || []);
      const payload = {
        season_id: seasonId,
        name: name || undefined,
        division_ids: selectedDivisions,
        seed_overrides: allRows.map((row) => ({ team_id: row.team_id, seed: row.seed })),
        excluded_team_ids: allRows.filter((row) => !row.included).map((row) => row.team_id),
        generate_bracket: true,
      };
      const result = await apiFetch('/tournaments', { method: 'POST', body: JSON.stringify(payload) }, token);
      setTournaments((current) => [result.tournament, ...current]);
      setMessage('Tournament bracket generated. Use the schedule editor below to assign dates, times, locations, and fields.');
    } catch (error: any) {
      setMessage(error?.message || 'Unable to create tournament.');
    } finally {
      setLoading(false);
    }
  };

  const publishTournament = async (id: string, publish: boolean) => {
    const result = await apiFetch(`/tournaments/${id}/${publish ? 'publish' : 'unpublish'}`, { method: 'POST', body: JSON.stringify({}) }, token);
    setTournaments((current) => current.map((item) => item.id === id ? result.tournament : item));
  };

  return <div className='space-y-5'>
    <div>
      <h1 className='text-2xl font-bold'>Tournament Builder</h1>
      <p className='text-sm text-slate-600'>Create single-elimination brackets seeded from Results & Standings. Tournament publication, scores, and advancement remain separate from the regular-season schedule.</p>
    </div>
    {message && <div className='rounded border bg-blue-50 p-3 text-sm text-blue-900'>{message}</div>}

    <section className='space-y-4 rounded border bg-white p-4'>
      <h2 className='text-xl font-semibold'>1. Create Tournament</h2>
      <div className='grid gap-3 md:grid-cols-3'>
        <label className='text-sm'>Season<select className='mt-1 w-full rounded border p-2' value={seasonId} onChange={(e) => setSeasonId(e.target.value)}>{seasons.map((season) => <option key={season.id} value={season.id}>{season.name}{season.is_active ? ' (Active)' : ''}</option>)}</select></label>
        <label className='text-sm md:col-span-2'>Tournament Name<input className='mt-1 w-full rounded border p-2' value={name} onChange={(e) => setName(e.target.value)} placeholder='Fall 2026 Tournament' /></label>
      </div>
      <div><div className='mb-2 text-sm font-semibold'>Divisions / Levels</div><div className='grid gap-2 md:grid-cols-3'>{divisions.map((division) => <label key={division.id} className='flex items-center gap-2 rounded border p-2 text-sm'><input type='checkbox' checked={selectedDivisions.includes(division.id)} onChange={() => toggleDivision(division.id)} /> {divisionLabel(division)}</label>)}</div></div>
      <div className='flex flex-wrap gap-2'><button className='rounded bg-slate-800 px-3 py-2 text-white disabled:opacity-60' disabled={loading} onClick={loadSeeds}>Load Teams from Results & Standings</button><button className='rounded bg-green-700 px-3 py-2 text-white disabled:opacity-60' disabled={loading} onClick={createTournament}>Generate Bracket & Save Tournament</button></div>
    </section>

    {selectedDivisionObjects.map((division) => <section key={division.id} className='space-y-3 rounded border bg-white p-4'>
      <h2 className='text-lg font-semibold'>{divisionLabel(division)} Seeds</h2>
      {warnings[division.id] && <div className='rounded border bg-amber-50 p-2 text-sm text-amber-800'>{warnings[division.id]}</div>}
      <div className='overflow-x-auto'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Included','Seed','Team','Community','Standings Rank','Source'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{(seedRows[division.id] || []).map((row) => <tr key={row.team_id} className='border-t'><td className='p-2'><input type='checkbox' checked={row.included} onChange={() => toggleTeam(division.id, row.team_id)} /></td><td className='p-2'><input className='w-20 rounded border p-1' type='number' min={1} value={row.seed} onChange={(e) => updateSeed(division.id, row.team_id, Number(e.target.value || 1))} /></td><td className='p-2 font-medium'>{row.team_name}</td><td className='p-2'>{row.community_name}</td><td className='p-2'>{row.original_standings_rank || '—'}</td><td className='p-2'>{row.seed_source}</td></tr>)}</tbody></table></div>
    </section>)}

    <section className='space-y-4 rounded border bg-white p-4'>
      <h2 className='text-xl font-semibold'>Tournament Views</h2>
      {tournaments.map((tournament) => {
        const activeView = viewModes[tournament.id] || 'schedule';
        return <div key={tournament.id} className='space-y-3 rounded border p-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <div><h3 className='text-lg font-semibold'>{tournament.name}</h3><p className='text-sm text-slate-600'>{tournament.status} · {tournament.is_published ? 'Published' : 'Unpublished'}</p></div>
            <div className='flex flex-wrap gap-2'>
              <div className='inline-flex rounded border p-1 text-sm'>
                <button className={`rounded px-3 py-1 ${activeView === 'schedule' ? 'bg-slate-900 text-white' : 'hover:bg-slate-50'}`} onClick={() => setViewModes((current) => ({ ...current, [tournament.id]: 'schedule' }))}>Schedule View</button>
                <button className={`rounded px-3 py-1 ${activeView === 'bracket' ? 'bg-slate-900 text-white' : 'hover:bg-slate-50'}`} onClick={() => setViewModes((current) => ({ ...current, [tournament.id]: 'bracket' }))}>Bracket View</button>
              </div>
              <button className='rounded border px-3 py-1' onClick={() => loadOptions()}>Refresh</button>
              <button className='rounded border px-3 py-1' onClick={() => publishTournament(tournament.id, true)}>Publish Tournament</button>
              <button className='rounded border px-3 py-1' onClick={() => publishTournament(tournament.id, false)}>Unpublish</button>
            </div>
          </div>
          {activeView === 'bracket' ? <TournamentBracket divisions={tournament.divisions} tournamentTitle={tournament.name} /> : tournament.divisions.map((division) => <div key={division.id} className='space-y-2'><h4 className='font-semibold'>{division.division_group} {division.division_name}</h4><div className='overflow-x-auto'><table className='min-w-full text-xs'><thead className='bg-slate-100 text-left'><tr>{['Round','Game #','Team 1 / Seed','Team 2 / Seed','Date','Time','Host Location','Field','Status','Score','Winner','Review'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{division.games.map((game) => <tr key={game.id} className='border-t'><td className='p-2'>{game.round_name}</td><td className='p-2'>{game.game_number}</td><td className='p-2'>{game.team_1_placeholder}</td><td className='p-2'>{game.team_2_placeholder}</td><td className='p-2'>{formatDisplayDate(game.date || '')}</td><td className='p-2'>{formatDisplayTime(game.time || '')}</td><td className='p-2'>{game.host_location_name || '—'}</td><td className='p-2'>{game.field_name || '—'}</td><td className='p-2'>{game.status}</td><td className='p-2'>{game.home_score ?? '—'} - {game.away_score ?? '—'}</td><td className='p-2'>{game.winner_team_name || '—'}</td><td className='p-2'>{game.needs_review ? 'Needs review' : '—'}</td></tr>)}</tbody></table></div></div>)}
        </div>;
      })}
    </section>
  </div>;
}
