'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ApiError, apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';
import { formatDisplayDate, formatDisplayDateTime, formatDisplayTime } from '@/lib/displayFormat';

export default function ManualScheduleBuilderPage() {
  const token = getToken();
  const searchParams = useSearchParams();
  const [options, setOptions] = useState<any>({ divisions: [], teams: [], host_locations: [], seasons: [], weeks: [], organizations: [], game_statuses: [] });
  const [seasonId, setSeasonId] = useState(searchParams.get('season_id') || '');
  const [weekId, setWeekId] = useState(searchParams.get('week_id') || '');
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
  const [allWeeklyMatchupsScheduled, setAllWeeklyMatchupsScheduled] = useState(false);
  const [noEligibleTeamMatchups, setNoEligibleTeamMatchups] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [autoFillPreview, setAutoFillPreview] = useState<any[]>([]);
  const [autoFillSkipped, setAutoFillSkipped] = useState<any[]>([]);
  const [autoFillLoading, setAutoFillLoading] = useState(false);
  const [schedulerDiagnostics, setSchedulerDiagnostics] = useState<any | null>(null);
  const [editGame, setEditGame] = useState<any | null>(null);
  const [moveGame, setMoveGame] = useState<any | null>(null);
  const [showClearScheduleModal, setShowClearScheduleModal] = useState(false);
  const [clearScheduleInput, setClearScheduleInput] = useState('');
  const [clearScheduleLoading, setClearScheduleLoading] = useState(false);
  const [showAutoScheduleSeasonModal, setShowAutoScheduleSeasonModal] = useState(false);
  const [clearExistingBeforeAutoSchedule, setClearExistingBeforeAutoSchedule] = useState(false);
  const [autoScheduleDryRun, setAutoScheduleDryRun] = useState(true);
  const [autoScheduleSeasonLoading, setAutoScheduleSeasonLoading] = useState(false);
  const [autoScheduleDiagnostics, setAutoScheduleDiagnostics] = useState<any | null>(null);
  const [optimizeSameCommunityHome, setOptimizeSameCommunityHome] = useState(true);
  const [repairDoubleHeaders, setRepairDoubleHeaders] = useState(true);
  const [reduceRepeatMatchups, setReduceRepeatMatchups] = useState(false);
  const [preserveTwoLocationLimit, setPreserveTwoLocationLimit] = useState(true);
  const [optimizerDryRun, setOptimizerDryRun] = useState(true);
  const [optimizerLoading, setOptimizerLoading] = useState(false);
  const [optimizerDiagnostics, setOptimizerDiagnostics] = useState<any | null>(null);

  const division = useMemo(() => options.divisions.find((d: any) => d.id === divisionId), [options, divisionId]);
  const divisionTeams = useMemo(() => options.teams.filter((t: any) => t.division_id === divisionId && t.is_active), [options, divisionId]);
  const seasonWeeks = useMemo(() => options.weeks.filter((w: any) => w.season_id === seasonId), [options, seasonId]);
  const canSave = Boolean(seasonId && weekId && divisionId && homeTeamId && awayTeamId && slotId);
  const hostLocationVerification = autoScheduleDiagnostics?.host_location_vs_home_team_verification || autoScheduleDiagnostics?.auto_schedule_diagnostics?.host_location_vs_home_team_verification || null;
  const hostOwnerAwayGames = hostLocationVerification?.host_owner_is_away_games || [];

  const getWeekOptionLabel = (week: any) => {
    const baseLabel = week.label || `Week ${week.week_number}`;
    if (!week.start_date) return baseLabel;
    const formattedDate = formatDisplayDate(week.start_date);
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
    setGames((scheduled.items || []).filter((game: any) => (game.status_code || game.game_status_code) !== 'UNSCHEDULED'));
  };

  const loadRecommendations = async () => {
    if (!divisionId || !weekId) return;
    const r: any = await apiFetch('/manual-schedule-builder/recommendations', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId, organization_id: organizationId || null, host_location_id: hostLocationId || null, home_team_id: homeTeamId || null, away_team_id: awayTeamId || null }) }, token);
    setSuggestedMatchups(r.suggested_matchups || []);
    setSuggestedSlots(r.suggested_slots || []);
    setSlots(r.suggested_slots || []);
    setAllWeeklyMatchupsScheduled(Boolean(r.all_available_weekly_matchups_scheduled));
    setNoEligibleTeamMatchups(Boolean(r.no_eligible_team_matchups));
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
                setSchedulerDiagnostics(res.diagnostics || null);
                const normalizedSkipped = (res.skipped || []).filter((s: any) => {
                  if ((s.reason || '').includes('Weekly game limit reached') && Number(s.active_games_counted || 0) === 0) return false;
                  return true;
                }).map((s: any) => {
                  if ((s.reason || '').includes('Weekly game limit reached') && Number(s.max_games_allowed || 0) > 0) {
                    return { ...s, reason: `Weekly game limit reached: ${s.max_games_allowed} of ${s.max_games_allowed} games already scheduled.` };
                  }
                  return s;
                });
                setAutoFillSkipped(normalizedSkipped);
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
                  <td className='p-2'>{formatDisplayDateTime(p.proposed_date, p.proposed_start_time)}</td>
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
                const maxGames = Number(applied.max_games ?? autoFillPreview.length ?? 0);
                const createdCount = Number(applied.created_count ?? applied.created_games ?? 0);
                setSuccess(`Applied auto-fill. Created ${createdCount} of ${maxGames} possible games.`);
                setAutoFillSkipped((applied.skipped || []).map((s: any) => ({ reason: s.reason || String(s) })));
                setSchedulerDiagnostics(applied.diagnostics || schedulerDiagnostics);
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
        {schedulerDiagnostics ? <div className='mt-3 rounded border bg-slate-50 p-3 text-sm'>
          <div className='font-semibold'>Scheduler Diagnostics</div>
          <ul className='mt-1 list-inside list-disc'>
            <li>Teams evaluated: {schedulerDiagnostics.teams_evaluated ?? 0}</li>
            <li>Slots evaluated: {schedulerDiagnostics.slots_evaluated ?? 0}</li>
            <li>Valid matchups found: {schedulerDiagnostics.valid_matchups_found ?? 0}</li>
            <li>Valid slot combinations found: {schedulerDiagnostics.valid_slot_combinations_found ?? 0}</li>
            <li>Rules relaxed: {schedulerDiagnostics.rules_relaxed ?? 0}</li>
            <li>Conflicts avoided: {schedulerDiagnostics.conflicts_avoided ?? 0}</li>
            <li>Final games created: {schedulerDiagnostics.final_games_created ?? 0}</li>
          </ul>
        </div> : null}
      </div>
      <div className='rounded border border-red-200 bg-red-50 p-3'>
        <h2 className='text-lg font-semibold text-red-800'>Administrative Management</h2>
        <p className='mt-1 text-sm text-red-700'>Use this only when you need to reset generated schedules for the selected season.</p>
        <button
          className='mt-3 mr-2 rounded border border-indigo-700 bg-indigo-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300 disabled:border-slate-300'
          disabled={!seasonId}
          onClick={() => {
            setError('');
            setSuccess('');
            setClearExistingBeforeAutoSchedule(false);
            setShowAutoScheduleSeasonModal(true);
          }}
        >
          Auto-Schedule Entire Season
        </button>
        <button
          className='mt-3 mr-2 rounded border border-emerald-700 bg-emerald-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300 disabled:border-slate-300'
          disabled={!seasonId || optimizerLoading}
          onClick={async () => {
            setError('');
            setSuccess('');
            setOptimizerLoading(true);
            try {
              const res: any = await apiFetch('/manual-schedule-builder/optimize-schedule', {
                method: 'POST',
                body: JSON.stringify({
                  season_id: seasonId,
                  optimize_same_community_home: optimizeSameCommunityHome,
                  repair_double_headers: repairDoubleHeaders,
                  reduce_repeat_matchups: reduceRepeatMatchups,
                  preserve_two_location_limit: preserveTwoLocationLimit,
                  dry_run: optimizerDryRun,
                }),
              }, token);
              setOptimizerDiagnostics(res);
              const summary = res.summary || {};
              setSuccess(`Optimization ${optimizerDryRun ? 'preview' : 'run'} completed. Proposed: ${Number(summary.same_community_repairs_proposed || 0) + Number(summary.double_header_repairs_proposed || 0)}, committed: ${Number(summary.same_community_repairs_committed || 0) + Number(summary.double_header_repairs_committed || 0)}, rejected: ${Number(summary.repairs_rejected || 0)}.`);
              await load();
            } catch (e: unknown) {
              setError(`Schedule optimization failed: ${extractError(e)}`);
            } finally {
              setOptimizerLoading(false);
            }
          }}
        >
          {optimizerLoading ? 'Running Optimization...' : 'Run Schedule Optimization'}
        </button>
        <button
          className='mt-3 rounded border border-red-600 bg-red-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300 disabled:border-slate-300'
          disabled={!seasonId}
          onClick={() => {
            setError('');
            setSuccess('');
            setClearScheduleInput('');
            setShowClearScheduleModal(true);
          }}
        >
          Clear All Scheduled Games
        </button>
        <div className='mt-3 grid gap-2 text-sm text-red-900 md:grid-cols-2'>
          <label className='flex items-center gap-2'><input type='checkbox' checked={optimizeSameCommunityHome} onChange={(e) => setOptimizeSameCommunityHome(e.target.checked)} />Optimize same-community home games</label>
          <label className='flex items-center gap-2'><input type='checkbox' checked={repairDoubleHeaders} onChange={(e) => setRepairDoubleHeaders(e.target.checked)} />Repair double headers</label>
          <label className='flex items-center gap-2'><input type='checkbox' checked={reduceRepeatMatchups} onChange={(e) => setReduceRepeatMatchups(e.target.checked)} />Reduce repeat matchups</label>
          <label className='flex items-center gap-2'><input type='checkbox' checked={preserveTwoLocationLimit} onChange={(e) => setPreserveTwoLocationLimit(e.target.checked)} />Preserve two-location limit</label>
          <label className='flex items-center gap-2 md:col-span-2'><input type='checkbox' checked={optimizerDryRun} onChange={(e) => setOptimizerDryRun(e.target.checked)} />Dry run (preview only, do not save)</label>
        </div>
        {optimizerDiagnostics ? <div className='mt-3 rounded border bg-white p-3 text-sm text-slate-800'>
          <div className='font-semibold'>Optimization Diagnostics</div>
          <div>Games reviewed: {optimizerDiagnostics.summary?.games_reviewed ?? 0}</div>
          <div>Same-community violations: {optimizerDiagnostics.summary?.same_community_violations_found ?? 0}</div>
          <div>Double-header violations: {optimizerDiagnostics.summary?.double_header_violations_found ?? 0}</div>
          <div>Repairs rejected: {optimizerDiagnostics.summary?.repairs_rejected ?? 0}</div>
        </div> : null}
      </div>

      <div className='rounded border p-3'>
        <h2 className='mb-2 text-lg font-semibold'>Suggested Matchups</h2>
        {noEligibleTeamMatchups && suggestedMatchups.length === 0 ? (
          <div className='mb-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-800'>
            No eligible team matchups could be generated.
          </div>
        ) : null}
        {allWeeklyMatchupsScheduled && suggestedMatchups.length === 0 && !noEligibleTeamMatchups ? (
          <div className='mb-2 rounded border border-blue-200 bg-blue-50 p-2 text-sm text-blue-800'>
            All available weekly matchups have been scheduled for this division/week.
          </div>
        ) : null}
        <table className='min-w-full text-sm'><thead><tr>{['Home Team', 'Away Team', 'Reason', 'Score'].map((h) => <th key={h} className='px-2 py-2 text-left font-bold'>{h}</th>)}</tr></thead><tbody>
          {suggestedMatchups.map((m: any, idx: number) => <tr key={`${m.home_team_id}-${m.away_team_id}-${idx}`} className='border-t'><td className='p-2'>{m.home_team_name}</td><td className='p-2'>{m.away_team_name}</td><td className='p-2'>{m.reason}</td><td className='p-2 font-semibold'>{m.score}</td></tr>)}
        </tbody></table>
      </div>

      <div className='overflow-auto rounded border'>
        <table className='min-w-full border-separate border-spacing-y-1 text-sm'><thead><tr>{['Date', 'Host Location', 'Field', 'Field Type', 'Start', 'End', 'Reason', 'Score', 'Recommendation', 'Select'].map((h) => <th key={h} className='px-2 py-2 text-center font-bold'>{h}</th>)}</tr></thead><tbody>
          {slots.map((s: any) => {
            const color = s.indicator === 'green' ? 'bg-emerald-50' : s.indicator === 'yellow' ? 'bg-yellow-50' : s.indicator === 'red' ? 'bg-red-50' : 'bg-white';
            return <tr key={s.slot_id || s.id} className={`align-middle ${slotId === (s.slot_id || s.id) ? 'ring-1 ring-blue-300' : ''} ${color}`}>
              <td className='px-2 py-3 text-center'>{formatDisplayDate(s.slot_date || s.available_date)}</td><td className='px-2 py-3 text-center'>{s.host_location_name}</td><td className='px-2 py-3 text-center'>{s.field_instance_name}</td><td className='px-2 py-3 text-center'>{s.field_type}</td><td className='px-2 py-3 text-center'>{formatDisplayTime(s.start_time)}</td><td className='px-2 py-3 text-center'>{formatDisplayTime(s.end_time)}</td><td className='px-2 py-3 text-center'>{s.reason || '-'}</td><td className='px-2 py-3 text-center font-semibold'>{s.score ?? '-'}</td><td className='px-2 py-3 text-center'>{s.rating || '-'}</td><td className='px-2 py-3 text-center'><button className='rounded border px-2 py-1 text-xs' onClick={() => setSlotId(s.slot_id || s.id)}>Use Recommended Slot</button></td>
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
              <td className='p-2'>{formatDisplayDate(g.game_date)}</td>
              <td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td>
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
                  setAutoFillSkipped([]);
                  setAutoFillPreview([]);
                  try {
                    setGames((prev) => prev.filter((game: any) => game.id !== g.id));
                    await apiFetch(`/schedule-management/games/${g.id}/unschedule`, { method: 'PATCH' }, token);
                    await load();
                    await loadRecommendations();
                    setSuccess('Game unscheduled.');
                  }
                  catch (e: unknown) {
                    await load();
                    await loadRecommendations();
                    setError(extractError(e));
                  }
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
          {slots.map((s: any) => <option key={s.slot_id || s.id} value={s.slot_id || s.id}>{formatDisplayDateTime(s.slot_date || s.available_date, s.start_time)} - {s.host_location_name} ({s.field_type})</option>)}
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
      {showClearScheduleModal ? <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4'>
        <div className='w-full max-w-xl rounded-lg bg-white p-4 shadow-xl'>
          <h3 className='text-lg font-semibold text-red-700'>Confirm Clear Scheduled Games</h3>
          <p className='mt-2 text-sm text-slate-700'>
            This will permanently remove all scheduled games for the selected season. This action cannot be undone.
          </p>
          <p className='mt-3 text-sm font-medium'>Type <span className='font-bold'>CLEAR SCHEDULE</span> to continue.</p>
          <input
            className='mt-2 w-full rounded border p-2'
            value={clearScheduleInput}
            onChange={(e) => setClearScheduleInput(e.target.value)}
            placeholder='CLEAR SCHEDULE'
          />
          <div className='mt-4 flex justify-end gap-2'>
            <button
              className='rounded border px-3 py-2'
              disabled={clearScheduleLoading}
              onClick={() => {
                setShowClearScheduleModal(false);
                setClearScheduleInput('');
              }}
            >
              Cancel
            </button>
            <button
              className='rounded border border-red-600 bg-red-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300'
              disabled={clearScheduleLoading || clearScheduleInput !== 'CLEAR SCHEDULE'}
              onClick={async () => {
                if (!seasonId) return;
                setError('');
                setSuccess('');
                setClearScheduleLoading(true);
                try {
                  await apiFetch(`/manual-schedule-builder/scheduled-games?season_id=${seasonId}`, { method: 'DELETE' }, token);
                  setShowClearScheduleModal(false);
                  setClearScheduleInput('');
                  await load();
                  await loadRecommendations();
                  setAutoFillPreview([]);
                  setAutoFillSkipped([]);
                  setSuccess('All scheduled games have been cleared.');
                } catch (e: unknown) {
                  setError(extractError(e));
                } finally {
                  setClearScheduleLoading(false);
                }
              }}
            >
              {clearScheduleLoading ? 'Clearing...' : 'Confirm Clear Schedule'}
            </button>
          </div>
        </div>
      </div> : null}
      {showAutoScheduleSeasonModal ? <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4'>
        <div className='w-full max-w-xl rounded-lg bg-white p-4 shadow-xl'>
          <h3 className='text-lg font-semibold text-indigo-700'>Confirm Full-Season Auto-Schedule</h3>
          <p className='mt-2 text-sm text-slate-700'>
            This will attempt to auto-schedule all unscheduled games for the selected season across all divisions and weeks.
          </p>
          <label className='mt-4 flex items-center gap-2 text-sm'>
            <input type='checkbox' checked={clearExistingBeforeAutoSchedule} onChange={(e) => setClearExistingBeforeAutoSchedule(e.target.checked)} />
            Clear existing scheduled games before running
          </label>
          <label className='mt-2 flex items-center gap-2 text-sm'>
            <input type='checkbox' checked={autoScheduleDryRun} onChange={(e) => setAutoScheduleDryRun(e.target.checked)} />
            Dry run (preview only, do not save)
          </label>
          <div className='mt-4 flex justify-end gap-2'>
            <button className='rounded border px-3 py-2' disabled={autoScheduleSeasonLoading} onClick={() => setShowAutoScheduleSeasonModal(false)}>Cancel</button>
            <button
              className='rounded border border-indigo-700 bg-indigo-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300'
              disabled={autoScheduleSeasonLoading || !seasonId}
              onClick={async () => {
                setError('');
                setSuccess('');
                // Keep the previous diagnostics visible while the next run is in progress.
                // They will be replaced by the HTTP 200 response even when the response status is warning/incomplete.
                setAutoScheduleSeasonLoading(true);
                try {
                  const res: any = await apiFetch('/manual-schedule-builder/auto-schedule-season', { method: 'POST', body: JSON.stringify({ season_id: seasonId, clear_existing: clearExistingBeforeAutoSchedule, dry_run: autoScheduleDryRun }) }, token);
                  setShowAutoScheduleSeasonModal(false);
                  await load();
                  await loadRecommendations();
                  setAutoScheduleDiagnostics(res);
                  const missing = (res.required_games_still_missing || []).length;
                  const warningCount = (res.warnings || []).length + (res.validation_errors || []).length;
                  const rootCauses = (res.root_cause_categories || res.auto_schedule_diagnostics?.root_cause_categories || []).join(', ');
                  const baseMessage = res.message || 'Auto-schedule completed.';
                  if (res.dry_run) {
                    setSuccess(res.message || `Dry run completed: ${Number(res.preview_games_count || 0)} games would be scheduled. No games were saved.`);
                  } else if (res.status === 'warning' || Number(res.committed_games_count ?? res.total_games_created ?? 0) === 0) {
                    setError(`${baseMessage}${rootCauses ? ` Root causes: ${rootCauses}.` : ''}`);
                  } else {
                    setSuccess(`${baseMessage} ${Number(res.committed_games_count ?? res.total_games_created ?? 0)} games scheduled, ${Number(res.games_skipped || 0)} placement attempts skipped, ${missing} required game groups still missing, ${warningCount} warnings/errors.`);
                  }
                } catch (e: unknown) {
                  setError(`Auto-schedule failed: ${extractError(e)}`);
                } finally {
                  setAutoScheduleSeasonLoading(false);
                }
              }}
            >
              {autoScheduleSeasonLoading ? 'Running...' : 'Run Auto-Schedule'}
            </button>
          </div>
        </div>
      </div> : null}
      {autoScheduleDiagnostics ? <details className='rounded border border-slate-300 bg-slate-50 p-3'>
        <summary className='cursor-pointer font-semibold text-slate-800'>Scheduling Diagnostics</summary>
        <div className='mt-3 space-y-3 text-sm'>
          <div><span className='font-semibold'>Status:</span> {autoScheduleDiagnostics.status || 'unknown'} — {autoScheduleDiagnostics.message || 'No message returned.'}</div>
          <div><span className='font-semibold'>Root causes:</span> {(autoScheduleDiagnostics.root_cause_categories || autoScheduleDiagnostics.auto_schedule_diagnostics?.root_cause_categories || ['unknown']).join(', ')}</div>
          <div><span className='font-semibold'>Dry run:</span> {autoScheduleDiagnostics.dry_run ? 'Yes' : 'No'}</div>
          <div><span className='font-semibold'>1. Games committed:</span> {Number(autoScheduleDiagnostics.committed_games_count ?? autoScheduleDiagnostics.total_games_created ?? 0)}</div>
          <div><span className='font-semibold'>Preview games:</span> {Number(autoScheduleDiagnostics.preview_games_count ?? autoScheduleDiagnostics.auto_schedule_diagnostics?.preview_games_count ?? 0)}</div>
          <div>
            <div className='font-semibold'>2. Placement attempts skipped: {Number(autoScheduleDiagnostics.games_skipped || 0)}</div>
            <ul className='list-inside list-disc'>
              {Object.entries(autoScheduleDiagnostics.skipped_attempts_by_reason || {}).map(([reason, count]: any) => <li key={reason}>{reason}: {count}</li>)}
            </ul>
          </div>
          {hostLocationVerification ? <section className='rounded border border-slate-200 bg-white p-3'>
            <h3 className='font-semibold'>Host Location vs Home Team Verification</h3>
            <div className='mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3'>
              <div>Total games checked: <span className='font-semibold'>{hostLocationVerification.total_games_checked ?? 0}</span></div>
              <div>Same-community games: <span className='font-semibold'>{hostLocationVerification.same_community_games ?? 0}</span></div>
              <div>Unknown location owner: <span className='font-semibold'>{hostLocationVerification.unknown_location_owner ?? 0}</span></div>
              <div>Host owner is home team: <span className='font-semibold'>{hostLocationVerification.host_owner_is_home_team ?? 0}</span></div>
              <div>Host owner is away team: <span className='font-semibold'>{hostLocationVerification.host_owner_is_away_team ?? 0}</span></div>
              <div>Neutral-site games: <span className='font-semibold'>{hostLocationVerification.neutral_site_games ?? 0}</span></div>
            </div>
            <div className='mt-3'>
              <div className='font-medium'>HOST_OWNER_IS_AWAY games</div>
              {hostOwnerAwayGames.length === 0 ? (
                <p className='mt-1 text-slate-700'>No host-owner-as-away games found.</p>
              ) : (
                <div className='mt-2 overflow-x-auto'>
                  <table className='min-w-full border text-xs'>
                    <thead>
                      <tr className='bg-slate-100'>
                        <th className='border p-1 text-left'>Date</th>
                        <th className='border p-1 text-left'>Time</th>
                        <th className='border p-1 text-left'>Division</th>
                        <th className='border p-1 text-left'>Location</th>
                        <th className='border p-1 text-left'>Field</th>
                        <th className='border p-1 text-left'>Location Owner</th>
                        <th className='border p-1 text-left'>Home Team</th>
                        <th className='border p-1 text-left'>Home Team Community</th>
                        <th className='border p-1 text-left'>Away Team</th>
                        <th className='border p-1 text-left'>Away Team Community</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hostOwnerAwayGames.map((game: any) => (
                        <tr key={game.game_id}>
                          <td className='border p-1'>{game.date ? formatDisplayDate(game.date) : 'N/A'}</td>
                          <td className='border p-1'>{game.start_time ? formatDisplayTime(game.start_time) : 'N/A'}</td>
                          <td className='border p-1'>{game.division || 'N/A'}</td>
                          <td className='border p-1'>{game.location || 'Unassigned'}</td>
                          <td className='border p-1'>{game.field || 'Unassigned'}</td>
                          <td className='border p-1'>{game.host_location_owner_community_name || 'Unknown'}</td>
                          <td className='border p-1'>{game.home_team || 'TBD'}</td>
                          <td className='border p-1'>{game.home_team_community_name || 'Unknown'}</td>
                          <td className='border p-1'>{game.away_team || 'TBD'}</td>
                          <td className='border p-1'>{game.away_team_community_name || 'Unknown'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section> : null}
          <div>
            <div className='font-semibold'>3. Required games still missing: {(autoScheduleDiagnostics.required_games_still_missing || []).length}</div>
            {(autoScheduleDiagnostics.required_games_still_missing || []).map((row: any, idx: number) => <div key={`${row.division}-${row.week}-${idx}`} className='ml-3'>{row.division} Week {row.week} — Required: {row.required_games}, Created: {row.created_games}, Missing: {row.missing_games}</div>)}
          </div>
          <div>
            <div className='font-semibold'>4. Warnings</div>
            <ul className='list-inside list-disc'>{(autoScheduleDiagnostics.warnings || []).map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
          </div>
          <div>
            <div className='font-semibold'>5. Validation failures</div>
            <ul className='list-inside list-disc'>{(autoScheduleDiagnostics.validation_errors || []).map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
          </div>
          {autoScheduleDiagnostics.auto_schedule_diagnostics ? <div>
            <div className='font-semibold'>6. Zero-game diagnostics</div>
            <div>Season: {autoScheduleDiagnostics.auto_schedule_diagnostics.season_name || 'Unknown'} ({autoScheduleDiagnostics.auto_schedule_diagnostics.season_id || 'no season id'})</div>
            <div>Weeks found: {autoScheduleDiagnostics.auto_schedule_diagnostics.weeks_found ?? 0}</div>
            <div>Regular season weeks found: {autoScheduleDiagnostics.auto_schedule_diagnostics.regular_season_weeks_found ?? autoScheduleDiagnostics.auto_schedule_diagnostics.weeks_evaluated ?? 0}</div>
            <div>Divisions evaluated: {autoScheduleDiagnostics.auto_schedule_diagnostics.divisions_evaluated ?? 0}</div>
            <div>Active teams: {autoScheduleDiagnostics.auto_schedule_diagnostics.active_teams_total ?? 0}</div>
            <div>Expected games: {autoScheduleDiagnostics.auto_schedule_diagnostics.expected_games_total ?? 0}</div>
            <div>Generated game groups: {autoScheduleDiagnostics.auto_schedule_diagnostics.generated_game_groups_total ?? 0}</div>
            <div>Placement attempts: {autoScheduleDiagnostics.auto_schedule_diagnostics.placement_attempts ?? 0}</div>
            <div>Attempted game groups: {autoScheduleDiagnostics.auto_schedule_diagnostics.attempted_game_groups ?? 0}</div>
            <div>Valid assignments found: {autoScheduleDiagnostics.auto_schedule_diagnostics.valid_assignments_found ?? 0}</div>
            <div>Preview assignments: {autoScheduleDiagnostics.auto_schedule_diagnostics.preview_assignments_count ?? 0}</div>
            <div>Committed assignments: {autoScheduleDiagnostics.auto_schedule_diagnostics.committed_assignments_count ?? 0}</div>
            <div>Failed validation count: {autoScheduleDiagnostics.auto_schedule_diagnostics.failed_validation_count ?? 0}</div>
            <div>Host availability count: {autoScheduleDiagnostics.auto_schedule_diagnostics.host_availability_total ?? 0}</div>
            <div>Generated slots by size: Small {autoScheduleDiagnostics.auto_schedule_diagnostics.generated_slots_by_field_size?.SMALL ?? 0}, Medium {autoScheduleDiagnostics.auto_schedule_diagnostics.generated_slots_by_field_size?.MEDIUM ?? 0}, Large {autoScheduleDiagnostics.auto_schedule_diagnostics.generated_slots_by_field_size?.LARGE ?? 0}</div>
            {autoScheduleDiagnostics.auto_schedule_diagnostics.missing_generated_slot_field_sizes?.length ? <div className='font-semibold text-rose-700'>Missing generated slot sizes: {autoScheduleDiagnostics.auto_schedule_diagnostics.missing_generated_slot_field_sizes.join(', ')}</div> : null}
            {Object.keys(autoScheduleDiagnostics.auto_schedule_diagnostics.failed_validation_reasons || {}).length ? <div>Failed validation reasons: {Object.entries(autoScheduleDiagnostics.auto_schedule_diagnostics.failed_validation_reasons || {}).map(([reason, count]: any) => `${reason}: ${count}`).join(', ')}</div> : null}
            {autoScheduleDiagnostics.auto_schedule_diagnostics.active_teams_by_division?.length ? <div className='mt-2'>
              <div className='font-semibold'>Active teams by division</div>
              <ul className='list-inside list-disc'>{autoScheduleDiagnostics.auto_schedule_diagnostics.active_teams_by_division.map((row: any) => <li key={row.division_id}>{row.division_name}: {row.active_team_count} teams</li>)}</ul>
            </div> : null}
            {autoScheduleDiagnostics.auto_schedule_diagnostics.generated_game_groups_by_division_week?.length ? <div className='mt-2 overflow-x-auto'>
              <div className='font-semibold'>Expected games vs generated game groups</div>
              <table className='mt-1 min-w-full border text-xs'>
                <thead><tr className='bg-slate-100'><th className='border p-1 text-left'>Division</th><th className='border p-1 text-left'>Week</th><th className='border p-1 text-right'>Expected</th><th className='border p-1 text-right'>Generated</th><th className='border p-1 text-right'>Existing scheduled</th></tr></thead>
                <tbody>{autoScheduleDiagnostics.auto_schedule_diagnostics.generated_game_groups_by_division_week.map((row: any) => <tr key={`${row.division_id}-${row.week}`}><td className='border p-1'>{row.division_name}</td><td className='border p-1'>{row.week}</td><td className='border p-1 text-right'>{row.expected_games ?? 0}</td><td className='border p-1 text-right'>{row.generated_game_groups ?? 0}</td><td className='border p-1 text-right'>{row.existing_scheduled_games ?? 0}</td></tr>)}</tbody>
              </table>
            </div> : null}
            {autoScheduleDiagnostics.auto_schedule_diagnostics.skipped_game_groups?.length ? <div className='mt-1'>Skipped game groups: {autoScheduleDiagnostics.auto_schedule_diagnostics.skipped_game_groups.map((row: any) => `${row.division_name} Week ${row.week} (${row.reason})`).join('; ')}</div> : null}
            {autoScheduleDiagnostics.auto_schedule_diagnostics.missing_division_week_generation?.length ? <div className='mt-1'>Missing division/week generation: {autoScheduleDiagnostics.auto_schedule_diagnostics.missing_division_week_generation.map((row: any) => `${row.division_name} Week ${row.week} (${row.reason})`).join('; ')}</div> : null}
          </div> : null}
          {(autoScheduleDiagnostics.division_week_schedule_diagnostics || autoScheduleDiagnostics.auto_schedule_diagnostics?.division_week_placement_diagnostics)?.length ? <div className='mt-3 overflow-x-auto'>
            <div className='font-semibold'>7. Division/week placement diagnostics</div>
            <table className='mt-1 min-w-full border text-xs'>
              <thead><tr className='bg-slate-100'><th className='border p-1 text-left'>Week</th><th className='border p-1 text-left'>Date</th><th className='border p-1 text-left'>Division</th><th className='border p-1 text-left'>Field size</th><th className='border p-1 text-right'>Teams</th><th className='border p-1 text-right'>Expected</th><th className='border p-1 text-right'>Generated</th><th className='border p-1 text-right'>Attempts</th><th className='border p-1 text-right'>Valid</th><th className='border p-1 text-right'>Scheduled</th><th className='border p-1 text-right'>Missing</th><th className='border p-1 text-left'>Doubleheader</th><th className='border p-1 text-right'>Compatible slots</th><th className='border p-1 text-left'>Skipped/rejected reasons</th></tr></thead>
              <tbody>{(autoScheduleDiagnostics.division_week_schedule_diagnostics || autoScheduleDiagnostics.auto_schedule_diagnostics?.division_week_placement_diagnostics || []).map((row: any, idx: number) => <tr key={`${row.division_id || row.division_name}-${row.week}-${idx}`} className={Number(row.missing_games || 0) > 0 ? 'bg-rose-50' : ''}><td className='border p-1'>{row.week}</td><td className='border p-1'>{row.week_start_date || row.date || ''}</td><td className='border p-1'>{row.division_name}</td><td className='border p-1'>{row.required_field_size}</td><td className='border p-1 text-right'>{row.active_team_count ?? (Array.isArray(row.active_teams) ? row.active_teams.length : row.active_teams ?? 0)}</td><td className='border p-1 text-right'>{row.expected_games ?? 0}</td><td className='border p-1 text-right'>{row.generated_game_groups ?? 0}</td><td className='border p-1 text-right'>{row.placement_attempts ?? 0}</td><td className='border p-1 text-right'>{row.valid_assignments_found ?? 0}</td><td className='border p-1 text-right'>{row.scheduled_games ?? 0}</td><td className='border p-1 text-right font-semibold'>{row.missing_games ?? 0}</td><td className='border p-1'>{row.doubleheader_team_selected || 'None'}</td><td className='border p-1 text-right'>{row.compatible_slot_count ?? row.compatible_slots_found ?? 0}</td><td className='border p-1'>{[...(row.skipped_placement_reasons || []), ...(row.rejected_placement_reasons || [])].slice(0, 4).join('; ')}</td></tr>)}</tbody>
            </table>
            {(autoScheduleDiagnostics.division_week_schedule_diagnostics || []).filter((row: any) => Number(row.missing_games || 0) > 0).map((row: any, idx: number) => <details key={`${row.division_id || row.division_name}-${row.week}-details-${idx}`} className='mt-2 rounded border border-rose-200 bg-white p-2'>
              <summary className='cursor-pointer font-medium text-rose-800'>{row.division_name} Week {row.week}: expected {row.expected_games ?? 0}, scheduled {row.scheduled_games ?? 0}</summary>
              <div className='mt-1'>Active teams: {Array.isArray(row.active_teams) ? row.active_teams.join(', ') : row.active_teams}</div>
              <div>Required matchups generated: {(row.required_matchups_generated || []).join('; ') || 'None'}</div>
              <div>Missing teams: {(row.missing_teams || []).join(', ') || 'None'}</div>
              <div>Compatible LARGE slots available: {row.compatible_large_slots_available ?? 'n/a'}</div>
              <ul className='mt-1 list-inside list-disc'>{(row.placement_attempt_details || []).slice(0, 50).map((attempt: any) => <li key={attempt.attempt_number}>{attempt.status}: {attempt.matchup || 'slot'} at {attempt.slot_date || ''} {attempt.start_time || ''} {attempt.host_location || ''} {attempt.field || ''} — {attempt.reason}</li>)}</ul>
            </details>)}
          </div> : null}
          {autoScheduleDiagnostics.slot_capacity_validation ? <div>
            <div className='font-semibold'>8. Generated slot capacity preflight</div>
            <div className='mt-1 text-slate-700'>Hosts evaluated and field-size slot counts before placement.</div>
            <div className='mt-2 space-y-2'>
              {(autoScheduleDiagnostics.slot_capacity_validation.validation_rows || []).map((row: any, idx: number) => <div key={`${row.week_start_date}-${idx}`} className='rounded border border-slate-200 bg-white p-2'>
                <div className='font-medium'>Week {row.week} ({row.week_start_date})</div>
                <div>Required games by size: Small {row.required_games_by_size?.SMALL ?? 0}, Medium {row.required_games_by_size?.MEDIUM ?? 0}, Large {row.required_games_by_size?.LARGE ?? 0}</div>
                <div>League-wide demand by size: Small {row.league_wide_demand_by_size?.SMALL ?? row.required_games_by_size?.SMALL ?? 0}, Medium {row.league_wide_demand_by_size?.MEDIUM ?? row.required_games_by_size?.MEDIUM ?? 0}, Large {row.league_wide_demand_by_size?.LARGE ?? row.required_games_by_size?.LARGE ?? 0}</div>
                <div>Generated slots by size: Small {row.generated_slots_by_size?.SMALL ?? 0}, Medium {row.generated_slots_by_size?.MEDIUM ?? 0}, Large {row.generated_slots_by_size?.LARGE ?? 0}</div>
                {row.active_divisions_included?.length ? <details className='mt-1'><summary className='cursor-pointer font-medium'>Generated Slots Demand Summary</summary><table className='mt-1 min-w-full border text-xs'><thead><tr className='bg-slate-100'><th className='border p-1 text-left'>Division</th><th className='border p-1 text-right'>Teams</th><th className='border p-1 text-right'>Expected</th><th className='border p-1 text-left'>Field size</th></tr></thead><tbody>{row.active_divisions_included.map((division: any) => <tr key={division.division_id}><td className='border p-1'>{division.division_name}</td><td className='border p-1 text-right'>{division.team_count ?? 0}</td><td className='border p-1 text-right'>{division.expected_games ?? 0}</td><td className='border p-1'>{division.field_size}</td></tr>)}</tbody></table></details> : null}
                {row.missing_field_sizes?.length ? <div className='font-semibold text-rose-700'>Missing slot sizes: {row.missing_field_sizes.join(', ')}</div> : null}
                <div>Selected hosts: {(row.selected_hosts || row.host_locations_evaluated)?.length ? (row.selected_hosts || row.host_locations_evaluated).join(', ') : 'None'}</div>
                {row.zero_slot_reason ? <div className='font-semibold text-rose-700'>Zero-slot reason: {row.zero_slot_reason}</div> : null}
                {row.generation_reasons?.length ? <ul className='mt-1 list-inside list-disc text-slate-600'>{row.generation_reasons.map((reason: string, reasonIdx: number) => <li key={reasonIdx}>{reason}</li>)}</ul> : null}
              </div>)}
            </div>
          </div> : null}
          <details className='rounded border border-slate-200 bg-white p-2'>
            <summary className='cursor-pointer font-semibold'>Raw auto-schedule diagnostics payload</summary>
            <pre className='mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-xs'>{JSON.stringify(autoScheduleDiagnostics, null, 2)}</pre>
          </details>
        </div>
      </details> : null}
    </div>
  );
}
