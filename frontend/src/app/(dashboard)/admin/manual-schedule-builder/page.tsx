'use client';

import { useEffect, useMemo, useState } from 'react';
import { ApiError, apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';

export default function ManualScheduleBuilderPage() {
  const token = getToken();
  const [options, setOptions] = useState<any>({ divisions: [], teams: [], host_locations: [], seasons: [], weeks: [], organizations: [], game_statuses: [] });
  const [seasonId, setSeasonId] = useState('');
  const [weekId, setWeekId] = useState('');
  const [divisionId, setDivisionId] = useState('');
  const [homeTeamId, setHomeTeamId] = useState('');
  const [awayTeamId, setAwayTeamId] = useState('');
  const [slotId, setSlotId] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [hostLocationId, setHostLocationId] = useState('');
  const [slots, setSlots] = useState<any[]>([]);
  const [games, setGames] = useState<any[]>([]);
  const [suggestedMatchups, setSuggestedMatchups] = useState<any[]>([]);
  const [suggestedSlots, setSuggestedSlots] = useState<any[]>([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [autoFillPreview, setAutoFillPreview] = useState<any[]>([]);
  const [autoFillSkipped, setAutoFillSkipped] = useState<any[]>([]);
  const [autoFillLoading, setAutoFillLoading] = useState(false);
  const [editGame, setEditGame] = useState<any | null>(null);
  const [moveGame, setMoveGame] = useState<any | null>(null);

  const division = useMemo(() => options.divisions.find((d: any) => d.id === divisionId), [options, divisionId]);
  const divisionTeams = useMemo(() => options.teams.filter((t: any) => t.division_id === divisionId && t.is_active), [options, divisionId]);
  const seasonWeeks = useMemo(() => options.weeks.filter((w: any) => w.season_id === seasonId), [options, seasonId]);
  const canSave = Boolean(seasonId && weekId && divisionId && homeTeamId && awayTeamId && slotId);

  const getWeekOptionLabel = (week: any) => {
    const baseLabel = week.label || `Week ${week.week_number}`;
    if (!week.start_date) return baseLabel;
    const parsed = new Date(week.start_date);
    const formattedDate = Number.isNaN(parsed.getTime())
      ? week.start_date
      : parsed.toLocaleDateString('en-US', {
          month: '2-digit',
          day: '2-digit',
          year: 'numeric',
          timeZone: 'UTC',
        });
    return `${baseLabel} — ${formattedDate}`;
  };

  const extractError = (e: unknown) => {
    if (e instanceof ApiError && e.details && typeof e.details === 'object') {
      const detail = (e.details as any).detail;
      if (Array.isArray(detail)) return detail.map((x: any) => x?.msg || JSON.stringify(x)).join('; ');
      if (typeof detail === 'string') return detail;
      if (detail && typeof detail === 'object') return JSON.stringify(detail);
      return e.message;
    }
    return e instanceof Error ? e.message : 'Request failed.';
  };

  const load = async () => {
    const opts: any = await apiFetch('/manual-schedule-builder/options', {}, token);
    const statuses: any = await apiFetch('/game-statuses?page_size=200', {}, token);
    setOptions({ ...opts, game_statuses: statuses.items || [] });
    const activeSeason = opts.seasons?.find((s: any) => s.is_active);
    if (!seasonId && activeSeason?.id) setSeasonId(activeSeason.id);
    if (!divisionId && opts.divisions?.length) setDivisionId(opts.divisions[0].id);
    const scheduled: any = await apiFetch('/games?page_size=300', {}, token);
    setGames(scheduled.items || []);
  };

  const loadRecommendations = async () => {
    if (!divisionId || !weekId) return;
    const r: any = await apiFetch('/manual-schedule-builder/recommendations', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId, organization_id: organizationId || null, host_location_id: hostLocationId || null, home_team_id: homeTeamId || null, away_team_id: awayTeamId || null }) }, token);
    setSuggestedMatchups(r.suggested_matchups || []);
    setSuggestedSlots(r.suggested_slots || []);
    setSlots(r.suggested_slots || []);
  };

  useEffect(() => { load().catch((e) => setError(extractError(e))); }, []);
  useEffect(() => { loadRecommendations().catch((e) => setError(extractError(e))); }, [seasonId, weekId, divisionId, organizationId, hostLocationId, homeTeamId, awayTeamId]);

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Manual Schedule Builder (Assisted)</h1>
      {error ? <div className='rounded border border-red-200 bg-red-50 p-2 text-red-700'>{error}</div> : null}
      {success ? <div className='rounded border border-emerald-200 bg-emerald-50 p-2 text-emerald-700'>{success}</div> : null}

      <div className='grid gap-2 md:grid-cols-8'>
        <select className='rounded border p-2' value={seasonId} onChange={(e) => { setSeasonId(e.target.value); setWeekId(''); }}><option value=''>Season</option>{options.seasons.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        <select className='rounded border p-2' value={weekId} onChange={(e) => setWeekId(e.target.value)}><option value=''>Week</option>{seasonWeeks.map((w: any) => <option key={w.id} value={w.id}>{getWeekOptionLabel(w)}</option>)}</select>
        <select className='rounded border p-2' value={divisionId} onChange={(e) => setDivisionId(e.target.value)}><option value=''>Division</option>{options.divisions.map((d: any) => <option key={d.id} value={d.id}>{getDivisionLabel(d)}</option>)}</select>
        <select className='rounded border p-2' value={organizationId} onChange={(e) => setOrganizationId(e.target.value)}><option value=''>Organization</option>{options.organizations?.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
        <select className='rounded border p-2' value={hostLocationId} onChange={(e) => setHostLocationId(e.target.value)}><option value=''>Host Location</option>{options.host_locations.map((h: any) => <option key={h.id} value={h.id}>{h.name}</option>)}</select>
        <select className='rounded border p-2' value={homeTeamId} onChange={(e) => setHomeTeamId(e.target.value)}><option value=''>Home Team</option>{divisionTeams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <select className='rounded border p-2' value={awayTeamId} onChange={(e) => setAwayTeamId(e.target.value)}><option value=''>Away Team</option>{divisionTeams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <button className='rounded bg-blue-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300' disabled={!canSave} onClick={async () => {
          setError(''); setSuccess('');
          try {
            await apiFetch('/manual-schedule-builder/assign', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId, home_team_id: homeTeamId, away_team_id: awayTeamId, generated_slot_id: slotId }) }, token);
            await load(); await loadRecommendations(); setSlotId(''); setSuccess('Game successfully scheduled.');
          } catch (e: unknown) { setError(extractError(e)); }
        }}>Save Game Assignment</button>
      </div>
      <div className='rounded border p-3'>
        <div className='flex items-center justify-between'>
          <h2 className='text-lg font-semibold'>Auto-Schedule Assistant</h2>
          <button
            className='rounded bg-indigo-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300'
            disabled={!seasonId || !weekId || !divisionId || autoFillLoading}
            onClick={async () => {
              setError('');
              setSuccess('');
              setAutoFillLoading(true);
              try {
                const res: any = await apiFetch('/manual-schedule-builder/auto-fill-preview', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId }) }, token);
                setAutoFillPreview(res.proposals || []);
                setAutoFillSkipped(res.skipped || []);
              } catch (e: unknown) {
                setError(extractError(e));
              } finally {
                setAutoFillLoading(false);
              }
            }}
          >
            Auto-Fill Selected Division/Week
          </button>
        </div>
        {autoFillPreview.length > 0 ? <div className='mt-3 space-y-3'>
          <div className='overflow-auto rounded border'>
            <table className='min-w-full text-sm'>
              <thead><tr>{['Proposed Matchup', 'Date/Time', 'Host Location', 'Field', 'Reason', 'Score'].map((h) => <th key={h} className='px-2 py-2 text-left'>{h}</th>)}</tr></thead>
              <tbody>
                {autoFillPreview.map((p: any, idx: number) => <tr key={`${p.slot_id}-${idx}`} className='border-t'>
                  <td className='p-2'>{p.proposed_matchup}</td>
                  <td className='p-2'>{p.proposed_date} {p.proposed_start_time}</td>
                  <td className='p-2'>{p.host_location}</td>
                  <td className='p-2'>{p.field}</td>
                  <td className='p-2'>{p.reason}</td>
                  <td className='p-2 font-semibold'>{p.score}</td>
                </tr>)}
              </tbody>
            </table>
          </div>
          <div className='flex gap-2'>
            <button className='rounded bg-emerald-700 px-3 py-2 text-white' onClick={async () => {
              setError('');
              setSuccess('');
              try {
                const applied: any = await apiFetch('/manual-schedule-builder/auto-fill-apply', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId, proposals: autoFillPreview }) }, token);
                setSuccess(`Applied auto-fill. Created ${applied.created_games} game(s), assigned ${applied.assigned_slots} slot(s).`);
                setAutoFillSkipped((applied.skipped || []).map((s: string) => ({ reason: s })));
                setAutoFillPreview([]);
                await load();
                await loadRecommendations();
              } catch (e: unknown) {
                setError(extractError(e));
              }
            }}>Apply Schedule</button>
            <button className='rounded border px-3 py-2' onClick={() => { setAutoFillPreview([]); setAutoFillSkipped([]); }}>Cancel</button>
          </div>
        </div> : null}
        {autoFillSkipped.length > 0 ? <div className='mt-3 rounded border bg-amber-50 p-2 text-sm'>
          <div className='font-semibold'>Skipped teams/matchups</div>
          <ul className='list-inside list-disc'>
            {autoFillSkipped.map((s: any, idx: number) => <li key={idx}>{s.reason || JSON.stringify(s)}</li>)}
          </ul>
        </div> : null}
      </div>

      <div className='rounded border p-3'>
        <h2 className='mb-2 text-lg font-semibold'>Suggested Matchups</h2>
        <table className='min-w-full text-sm'><thead><tr>{['Home Team', 'Away Team', 'Reason', 'Score'].map((h) => <th key={h} className='px-2 py-2 text-left font-bold'>{h}</th>)}</tr></thead><tbody>
          {suggestedMatchups.map((m: any, idx: number) => <tr key={`${m.home_team_id}-${m.away_team_id}-${idx}`} className='border-t'><td className='p-2'>{m.home_team_name}</td><td className='p-2'>{m.away_team_name}</td><td className='p-2'>{m.reason}</td><td className='p-2 font-semibold'>{m.score}</td></tr>)}
        </tbody></table>
      </div>

      <div className='overflow-auto rounded border'>
        <table className='min-w-full border-separate border-spacing-y-1 text-sm'><thead><tr>{['Date', 'Host Location', 'Field', 'Field Type', 'Start', 'End', 'Reason', 'Score', 'Recommendation', 'Select'].map((h) => <th key={h} className='px-2 py-2 text-center font-bold'>{h}</th>)}</tr></thead><tbody>
          {slots.map((s: any) => {
            const color = s.indicator === 'green' ? 'bg-emerald-50' : s.indicator === 'yellow' ? 'bg-yellow-50' : s.indicator === 'red' ? 'bg-red-50' : 'bg-white';
            return <tr key={s.slot_id || s.id} className={`align-middle ${slotId === (s.slot_id || s.id) ? 'ring-1 ring-blue-300' : ''} ${color}`}>
              <td className='px-2 py-3 text-center'>{s.slot_date || s.available_date}</td><td className='px-2 py-3 text-center'>{s.host_location_name}</td><td className='px-2 py-3 text-center'>{s.field_instance_name}</td><td className='px-2 py-3 text-center'>{s.field_type}</td><td className='px-2 py-3 text-center'>{s.start_time}</td><td className='px-2 py-3 text-center'>{s.end_time}</td><td className='px-2 py-3 text-center'>{s.reason || '-'}</td><td className='px-2 py-3 text-center font-semibold'>{s.score ?? '-'}</td><td className='px-2 py-3 text-center'>{s.rating || '-'}</td><td className='px-2 py-3 text-center'><button className='rounded border px-2 py-1 text-xs' onClick={() => setSlotId(s.slot_id || s.id)}>Use Recommended Slot</button></td>
            </tr>;
          })}
        </tbody></table>
      </div>
      <div className='rounded border p-3'>
        <h2 className='mb-2 text-lg font-semibold'>Scheduled Games</h2>
        <table className='min-w-full text-sm'>
          <thead><tr>{['Date', 'Time', 'Division', 'Matchup', 'Host Location', 'Field', 'Status', 'Actions'].map((h) => <th key={h} className='px-2 py-2 text-left'>{h}</th>)}</tr></thead>
          <tbody>
            {games.map((g: any) => <tr key={g.id} className='border-t'>
              <td className='p-2'>{g.game_date || '-'}</td>
              <td className='p-2'>{g.kickoff_time || '-'}</td>
              <td className='p-2'>{g.division_name || 'Unknown Division'}</td>
              <td className='p-2'>{g.home_team_name || 'Unknown Team'} vs {g.away_team_name || 'Unknown Team'}</td>
              <td className='p-2'>{g.host_location_name || '-'}</td>
              <td className='p-2'>{g.field_instance_name || '-'}</td>
              <td className='p-2'>{g.game_status_code}</td>
              <td className='p-2 space-x-2'>
                <button className='rounded border px-2 py-1 text-xs' onClick={() => setEditGame({ ...g, division_id: g.division_id })}>Edit</button>
                <button className='rounded border px-2 py-1 text-xs' onClick={() => setMoveGame(g)}>Move</button>
                <button className='rounded border border-red-300 px-2 py-1 text-xs text-red-700' onClick={async () => {
                  if (!window.confirm('Remove this scheduled game?')) return;
                  setError('');
                  try { await apiFetch(`/schedule-management/games/${g.id}/unschedule`, { method: 'PATCH' }, token); await load(); await loadRecommendations(); setSuccess('Game unscheduled.'); }
                  catch (e: unknown) { setError(extractError(e)); }
                }}>Delete / Unschedule</button>
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>
      {editGame ? <div className='rounded border bg-slate-50 p-3'>
        <h3 className='mb-2 font-semibold'>Edit Game</h3>
        <div className='grid gap-2 md:grid-cols-5'>
          <select className='rounded border p-2' value={editGame.division_id || ''} onChange={(e) => setEditGame({ ...editGame, division_id: e.target.value, home_team_id: '', away_team_id: '' })}><option value=''>Division</option>{options.divisions.map((d: any) => <option key={d.id} value={d.id}>{getDivisionLabel(d)}</option>)}</select>
          <select className='rounded border p-2' value={editGame.home_team_id} onChange={(e) => setEditGame({ ...editGame, home_team_id: e.target.value })}><option value=''>Home Team</option>{options.teams.filter((t: any) => t.division_id === editGame.division_id).map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
          <select className='rounded border p-2' value={editGame.away_team_id} onChange={(e) => setEditGame({ ...editGame, away_team_id: e.target.value })}><option value=''>Away Team</option>{options.teams.filter((t: any) => t.division_id === editGame.division_id).map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
          <select className='rounded border p-2' value={editGame.game_status_id} onChange={(e) => setEditGame({ ...editGame, game_status_id: e.target.value })}><option value=''>Status</option>{options.game_statuses?.map((s: any) => <option key={s.id} value={s.id}>{s.label}</option>)}</select>
          <div className='rounded border p-2 text-xs text-slate-500'>Notes editing not available in current game schema.</div>
        </div>
        <div className='mt-2 flex gap-2'>
          <button className='rounded bg-blue-600 px-3 py-2 text-white' onClick={async () => {
            setError('');
            if (editGame.home_team_id === editGame.away_team_id) { setError('Home and away cannot be the same.'); return; }
            const home = options.teams.find((t: any) => t.id === editGame.home_team_id);
            const away = options.teams.find((t: any) => t.id === editGame.away_team_id);
            if (!home || !away || home.division_id !== editGame.division_id || away.division_id !== editGame.division_id) { setError('Teams must belong to selected division.'); return; }
            const dup = games.some((g: any) => g.id !== editGame.id && ((g.home_team_id === editGame.home_team_id && g.away_team_id === editGame.away_team_id) || (g.home_team_id === editGame.away_team_id && g.away_team_id === editGame.home_team_id)));
            if (dup && !window.confirm('Duplicate matchup warning: proceed?')) return;
            try {
              await apiFetch(`/games/${editGame.id}`, { method: 'PATCH', body: JSON.stringify({ season_id: editGame.season_id, week_id: editGame.week_id, division_id: editGame.division_id, home_team_id: editGame.home_team_id, away_team_id: editGame.away_team_id, field_id: editGame.field_id, game_status_id: editGame.game_status_id, game_date: editGame.game_date, kickoff_time: editGame.kickoff_time }) }, token);
              setEditGame(null); await load(); await loadRecommendations(); setSuccess('Game updated.');
            } catch (e: unknown) { setError(extractError(e)); }
          }}>Save Edit</button>
          <button className='rounded border px-3 py-2' onClick={() => setEditGame(null)}>Cancel</button>
        </div>
      </div> : null}
      {moveGame ? <div className='rounded border bg-slate-50 p-3'>
        <h3 className='mb-2 font-semibold'>Move Game</h3>
        <select className='rounded border p-2' value={slotId} onChange={(e) => setSlotId(e.target.value)}>
          <option value=''>Select OPEN slot</option>
          {slots.map((s: any) => <option key={s.slot_id || s.id} value={s.slot_id || s.id}>{s.slot_date || s.available_date} {s.start_time} - {s.host_location_name} ({s.field_type})</option>)}
        </select>
        <div className='mt-2 flex gap-2'>
          <button className='rounded bg-blue-600 px-3 py-2 text-white' onClick={async () => {
            if (!slotId) return;
            setError('');
            try { await apiFetch(`/schedule-management/games/${moveGame.id}/move`, { method: 'PATCH', body: JSON.stringify({ generated_slot_id: slotId }) }, token); setMoveGame(null); setSlotId(''); await load(); await loadRecommendations(); setSuccess('Game moved.'); }
            catch (e: unknown) { setError(extractError(e)); }
          }}>Save Move</button>
          <button className='rounded border px-3 py-2' onClick={() => { setMoveGame(null); setSlotId(''); }}>Cancel</button>
        </div>
      </div> : null}
    </div>
  );
}
