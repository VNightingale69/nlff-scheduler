'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { type AuthUser, getAuthUser, getToken } from '@/lib/auth';

type MatrixDate = {
  game_date: string;
  primary_game_date?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  week_id: string | null;
  week_number: number | null;
  label: string;
  week_label?: string | null;
  is_postseason: boolean;
  status: string | null;
  date_type?: string | null;
};

type MatrixCell = {
  status: string;
  locked: boolean;
  reason: string | null;
  availability_id: string | null;
  has_saved_availability: boolean;
  available_slot_count: number;
  capacity_by_size: Record<string, number>;
};

type MatrixRow = {
  community_id: string;
  community_name: string;
  host_location_id: string;
  host_location_name: string;
  surface_type: string;
  capacity_by_size: Record<string, number>;
  cells: Record<string, MatrixCell>;
};

type WeeklyHostPlanDecisionSummary = {
  diagnostic_label?: string;
  selected_communities: string[];
  excluded_communities: string[];
  total_games_required: number;
  selected_total_capacity: number;
  selected_small_capacity: number;
  selected_medium_capacity: number;
  selected_large_capacity: number;
  doubleheader_adjacency_available: boolean;
  home_field_requirement_satisfied: boolean;
  additional_host_needed: boolean;
  reason_additional_host_was_added: string | null;
};

type WeeklySummary = MatrixDate & {
  total_games_required: number;
  available_communities?: string[];
  available_locations?: Array<{ community_name: string; host_location_name: string }>;
  expected_host_communities?: string[];
  games_required_by_size: Record<string, number>;
  selected_communities: string[];
  selected_fields: Array<{ community_name: string; host_location_name: string }>;
  excluded_available_fields: Array<{ community_name: string; host_location_name: string }>;
  estimated_capacity_by_field_size: Record<string, number>;
  target_game_split: Record<string, number>;
  validation_warnings: string[];
  weekly_host_plan_decision_summary?: WeeklyHostPlanDecisionSummary;
};

type MatrixResponse = {
  season: { id: string; name: string };
  dates: MatrixDate[];
  rows: MatrixRow[];
  summaries: WeeklySummary[];
};

const HOST_PLAN_SELECTION_ADMIN_EMAIL = 'admin@example.com';
const HOST_PLAN_SELECTION_PERMISSION_MESSAGE = 'Only admin@example.com can modify host plan selections.';
const CYCLE = ['AVAILABLE', 'SELECTED', 'EXCLUDED'];
const LABELS: Record<string, string> = {
  BLANK: '',
  NOT_AVAILABLE: '',
  AVAILABLE: 'X',
  SELECTED: '✓',
  EXCLUDED: 'O',
  LOCKED: 'L',
  OVERFLOW: 'OF',
  BLOCKED_CAPACITY: 'BC',
  BLOCKED_ROTATION: 'BR',
  BLOCKED_FIELD_SIZE: 'BF',
};

const CELL_CLASSES: Record<string, string> = {
  BLANK: 'bg-slate-100 text-slate-300',
  NOT_AVAILABLE: 'bg-slate-100 text-slate-300',
  AVAILABLE: 'bg-white text-slate-800 hover:bg-slate-50',
  SELECTED: 'bg-emerald-100 text-emerald-800 ring-1 ring-emerald-300',
  EXCLUDED: 'bg-slate-200 text-slate-500',
  LOCKED: 'bg-blue-100 text-blue-800 ring-2 ring-blue-500 font-bold',
  OVERFLOW: 'bg-amber-100 text-amber-800 ring-1 ring-amber-300',
  BLOCKED_CAPACITY: 'bg-rose-100 text-rose-700',
  BLOCKED_ROTATION: 'bg-orange-100 text-orange-700',
  BLOCKED_FIELD_SIZE: 'bg-purple-100 text-purple-700',
};

const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function formatDate(value: string) {
  const [yearText, monthText, dayText] = value.split('-');
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (!year || !month || !day || month < 1 || month > 12) return value;
  return `${MONTH_LABELS[month - 1]} ${day}`;
}

function emptyMatrix(): MatrixResponse {
  return { season: { id: '', name: '' }, dates: [], rows: [], summaries: [] };
}

function extractError(error: unknown) {
  return error instanceof Error ? error.message : 'Request failed.';
}

export default function HostAvailabilityMatrix() {
  const token = getToken();
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [seasons, setSeasons] = useState<Array<{ id: string; name: string }>>([]);
  const [seasonId, setSeasonId] = useState('');
  const [matrix, setMatrix] = useState<MatrixResponse>(emptyMatrix());
  const [selectedDate, setSelectedDate] = useState('');
  const [weekFilterDate, setWeekFilterDate] = useState('');
  const [communityFilter, setCommunityFilter] = useState('');
  const [locationFilter, setLocationFilter] = useState('');
  const [dirtyCells, setDirtyCells] = useState<Record<string, MatrixCell>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    setCurrentUser(getAuthUser());
  }, []);

  const canModifyMatrix = currentUser?.email?.trim().toLowerCase() === HOST_PLAN_SELECTION_ADMIN_EMAIL;


  useEffect(() => {
    apiFetch('/seasons?page_size=100', {}, token).then((res: any) => {
      const items = res.items || [];
      setSeasons(items);
      const params = new URLSearchParams(window.location.search);
      const requestedSeasonId = params.get('season_id');
      const active = items.find((season: any) => season.id === requestedSeasonId) || items.find((season: any) => season.is_active) || items[0];
      if (active) setSeasonId(active.id);
    }).catch((err: unknown) => setError(extractError(err)));
  }, [token]);

  const loadMatrix = async () => {
    if (!seasonId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`/host-availability-matrix?season_id=${seasonId}`, {}, token) as MatrixResponse;
      setMatrix(res);
      const params = new URLSearchParams(window.location.search);
      const requestedDate = params.get('game_date') || params.get('primary_game_date') || params.get('start_date');
      const hasRequestedDate = Boolean(requestedDate && res.dates.some((date) => date.game_date === requestedDate));

      // The matrix should always open in the league-wide season view. Query-string
      // dates may focus the weekly summary, but filters remain opt-in controls.
      setWeekFilterDate('');
      setCommunityFilter('');
      setLocationFilter('');
      setSelectedDate((current) => {
        if (hasRequestedDate) return requestedDate as string;
        if (current && res.dates.some((date) => date.game_date === current)) return current;
        return res.dates[0]?.game_date || '';
      });
      setDirtyCells({});
    } catch (err) {
      setError(extractError(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMatrix();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seasonId]);

  const selectedSummary = useMemo(
    () => matrix.summaries.find((summary) => summary.game_date === selectedDate),
    [matrix.summaries, selectedDate]
  );

  const filteredDates = useMemo(() => {
    if (!weekFilterDate) return matrix.dates;
    return matrix.dates.filter((date) => date.game_date === weekFilterDate);
  }, [matrix.dates, weekFilterDate]);

  const filteredRows = useMemo(() => {
    const communityNeedle = communityFilter.trim().toLowerCase();
    const locationNeedle = locationFilter.trim().toLowerCase();
    return matrix.rows.filter((row) => {
      const communityMatch = !communityNeedle || row.community_name.toLowerCase().includes(communityNeedle);
      const locationMatch = !locationNeedle || row.host_location_name.toLowerCase().includes(locationNeedle);
      return communityMatch && locationMatch;
    });
  }, [communityFilter, locationFilter, matrix.rows]);

  const groupedRows = useMemo(() => {
    const groups: Array<{ community: string; rows: MatrixRow[] }> = [];
    for (const row of filteredRows) {
      const last = groups[groups.length - 1];
      if (!last || last.community !== row.community_name) groups.push({ community: row.community_name, rows: [row] });
      else last.rows.push(row);
    }
    return groups;
  }, [filteredRows]);

  const cellKey = (row: MatrixRow, date: MatrixDate) => `${row.host_location_id}:${date.game_date}`;

  const getCell = (row: MatrixRow, date: MatrixDate) => dirtyCells[cellKey(row, date)] || row.cells[date.game_date] || { status: 'NOT_AVAILABLE', locked: false, reason: null, availability_id: null, has_saved_availability: false, available_slot_count: 0, capacity_by_size: {} };

  const selectedSummaryDetails = useMemo(() => {
    if (!selectedDate) return null;
    const availableCommunities = new Set<string>();
    const availableLocations: Array<{ community_name: string; host_location_name: string }> = [];
    const selectedLocations: Array<{ community_name: string; host_location_name: string }> = [];
    const excludedLocations: Array<{ community_name: string; host_location_name: string }> = [];
    const capacity = { SMALL: 0, MEDIUM: 0, LARGE: 0 };

    for (const row of filteredRows) {
      const date = matrix.dates.find((item) => item.game_date === selectedDate);
      if (!date) continue;
      const cell = getCell(row, date);
      const status = cell.locked ? 'LOCKED' : cell.status;
      if (cell.has_saved_availability || status === 'OVERFLOW') {
        availableCommunities.add(row.community_name);
        availableLocations.push({ community_name: row.community_name, host_location_name: row.host_location_name });
      }
      if (['SELECTED', 'LOCKED', 'OVERFLOW'].includes(status)) {
        selectedLocations.push({ community_name: row.community_name, host_location_name: row.host_location_name });
        for (const size of Object.keys(capacity) as Array<keyof typeof capacity>) {
          capacity[size] += Number((cell.capacity_by_size || row.capacity_by_size || {})[size] || 0);
        }
      }
      if (status === 'EXCLUDED') excludedLocations.push({ community_name: row.community_name, host_location_name: row.host_location_name });
    }

    return {
      availableCommunities: Array.from(availableCommunities).sort(),
      availableLocations,
      selectedLocations,
      excludedLocations,
      capacity,
      expectedHostCommunities: Array.from(new Set(selectedLocations.map((field) => field.community_name))).sort(),
    };
  }, [dirtyCells, filteredRows, matrix.dates, selectedDate]);

  const visibleSelectedFields = selectedSummaryDetails?.selectedLocations || selectedSummary?.selected_fields || [];
  const visibleExcludedFields = selectedSummaryDetails?.excludedLocations || selectedSummary?.excluded_available_fields || [];
  const visibleCapacity: Record<string, number> = selectedSummaryDetails?.capacity || selectedSummary?.estimated_capacity_by_field_size || {};

  const updateCell = (row: MatrixRow, date: MatrixDate, cell: MatrixCell) => {
    setDirtyCells((prev) => ({ ...prev, [cellKey(row, date)]: cell }));
  };

  const handleCellClick = (row: MatrixRow, date: MatrixDate, event: React.MouseEvent<HTMLButtonElement>) => {
    if (!canModifyMatrix) {
      setMessage(HOST_PLAN_SELECTION_PERMISSION_MESSAGE);
      return;
    }
    setSelectedDate(date.game_date);
    const cell = getCell(row, date);
    if (event.shiftKey) {
      if (!cell.has_saved_availability && cell.status === 'NOT_AVAILABLE') return;
      updateCell(row, date, { ...cell, status: cell.status === 'LOCKED' ? 'SELECTED' : 'LOCKED', locked: cell.status !== 'LOCKED' });
      return;
    }
    if (!cell.has_saved_availability && cell.status === 'NOT_AVAILABLE') return;
    const current = cell.status === 'LOCKED' ? 'SELECTED' : cell.status;
    const next = CYCLE[(CYCLE.indexOf(current) + 1) % CYCLE.length] || 'AVAILABLE';
    updateCell(row, date, { ...cell, status: next, locked: next === 'LOCKED' ? true : cell.locked && next === 'SELECTED' });
  };


  const handleCellMenu = (row: MatrixRow, date: MatrixDate, event: React.MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (!canModifyMatrix) {
      setMessage(HOST_PLAN_SELECTION_PERMISSION_MESSAGE);
      return;
    }
    setSelectedDate(date.game_date);
    const cell = getCell(row, date);
    const action = window.prompt('Cell menu: type LOCK, UNLOCK, OVERFLOW, NOTE, or CLEAR', cell.locked || cell.status === 'LOCKED' ? 'UNLOCK' : 'OVERFLOW');
    const normalized = (action || '').trim().toUpperCase();
    if (!normalized) return;
    if (normalized === 'LOCK') {
      if (!cell.has_saved_availability && cell.status === 'NOT_AVAILABLE') return;
      updateCell(row, date, { ...cell, status: 'LOCKED', locked: true });
      return;
    }
    if (normalized === 'UNLOCK') {
      updateCell(row, date, { ...cell, status: cell.status === 'LOCKED' ? 'SELECTED' : cell.status, locked: false });
      return;
    }
    if (normalized === 'OVERFLOW') {
      const reason = window.prompt('Overflow reason/note', cell.reason || 'Added as overflow by scheduler');
      updateCell(row, date, { ...cell, status: 'OVERFLOW', locked: false, reason: reason || cell.reason || 'Added as overflow by scheduler' });
      return;
    }
    if (normalized === 'NOTE') {
      const reason = window.prompt('Reason/note', cell.reason || '');
      updateCell(row, date, { ...cell, reason: reason || null });
      return;
    }
    if (normalized === 'CLEAR') {
      updateCell(row, date, { ...cell, status: cell.has_saved_availability ? 'AVAILABLE' : 'NOT_AVAILABLE', locked: false, reason: null });
    }
  };

  const saveChanges = async () => {
    if (!canModifyMatrix) {
      setMessage(HOST_PLAN_SELECTION_PERMISSION_MESSAGE);
      return;
    }
    const selections = Object.entries(dirtyCells).map(([key, cell]) => {
      const [hostLocationId, gameDate] = key.split(':');
      const row = matrix.rows.find((item) => item.host_location_id === hostLocationId);
      const dateInfo = matrix.dates.find((item) => item.game_date === gameDate);
      return row && dateInfo ? {
        season_id: seasonId,
        week_id: dateInfo.week_id,
        game_date: gameDate,
        community_id: row.community_id,
        host_location_id: row.host_location_id,
        availability_id: cell.availability_id,
        status: cell.status,
        locked: cell.locked || cell.status === 'LOCKED',
        reason: cell.reason,
      } : null;
    }).filter(Boolean);
    if (!selections.length) {
      setMessage('No matrix changes to save.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const res: any = await apiFetch('/host-availability-matrix/save', { method: 'POST', body: JSON.stringify({ season_id: seasonId, selections }) }, token);
      setMessage(`Saved ${res.saved} host plan selection${res.saved === 1 ? '' : 's'}.`);
      await loadMatrix();
    } catch (err) {
      setError(extractError(err));
    } finally {
      setSaving(false);
    }
  };

  const runAction = async (action: 'generate' | 'lock' | 'unlock' | 'clear' | 'auto') => {
    if (!canModifyMatrix) {
      setMessage(HOST_PLAN_SELECTION_PERMISSION_MESSAGE);
      return;
    }
    if (!seasonId || !selectedDate) return;
    setError('');
    setMessage('');
    try {
      if (action === 'generate') {
        const result: any = await apiFetch('/host-availability-matrix/generate-suggested-plan', { method: 'POST', body: JSON.stringify({ season_id: seasonId, game_date: selectedDate }) }, token);
        setMessage(result?.decision_message || 'Generated a suggested host plan for the selected week.');
      } else if (action === 'lock' || action === 'unlock') {
        await apiFetch('/host-availability-matrix/week-lock', { method: 'POST', body: JSON.stringify({ season_id: seasonId, game_date: selectedDate, locked: action === 'lock' }) }, token);
        setMessage(action === 'lock' ? 'Selected week locked.' : 'Selected week unlocked.');
      } else if (action === 'clear') {
        await apiFetch(`/host-availability-matrix/selections?season_id=${seasonId}&game_date=${selectedDate}`, { method: 'DELETE' }, token);
        setMessage('Cleared host plan selections for the selected week. Availability records were not deleted.');
      } else {
        await apiFetch('/manual-schedule-builder/auto-schedule-season', { method: 'POST', body: JSON.stringify({ season_id: seasonId, use_host_plan_selections: true }) }, token);
        setMessage('Auto-schedule started using selected, locked, and overflow fields only.');
      }
      await loadMatrix();
    } catch (err) {
      setError(extractError(err));
    }
  };

  return <div className='space-y-4'>
    <div className='rounded border bg-white p-4 shadow-sm'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <div>
          <p className='text-sm font-semibold uppercase tracking-wide text-slate-500'>Admin → Scheduling → Host Availability Matrix</p>
          <h1 className='text-2xl font-bold text-slate-900'>Host Availability Matrix</h1>
          <p className='text-sm text-slate-600'>Season-wide scheduler planning tool for communities, host locations, and game dates. Select fields for auto-schedule, exclude available fields, and lock weekly host plans without deleting community availability.</p>
        </div>
        <select className='rounded border p-2' value={seasonId} onChange={(e) => setSeasonId(e.target.value)}>
          {seasons.map((season) => <option key={season.id} value={season.id}>{season.name}</option>)}
        </select>
      </div>
      {!canModifyMatrix ? <div className='mt-4 rounded bg-amber-50 p-3 text-sm font-medium text-amber-900'>{HOST_PLAN_SELECTION_PERMISSION_MESSAGE}</div> : null}
      <div className='mt-4 grid gap-3 md:grid-cols-4'>
        <label className='text-sm font-medium text-slate-700'>Weekly filter
          <select className='mt-1 w-full rounded border p-2 font-normal' value={weekFilterDate} onChange={(e) => { setWeekFilterDate(e.target.value); if (e.target.value) setSelectedDate(e.target.value); }}>
            <option value=''>All season dates</option>
            {matrix.dates.map((date) => <option key={date.game_date} value={date.game_date}>{date.label || `Week ${date.week_number ?? '—'}`} · {formatDate(date.game_date)} · {(date.date_type || 'REGULAR_SEASON').replace('_', ' ')}</option>)}
          </select>
        </label>
        <label className='text-sm font-medium text-slate-700'>Filter by community
          <input className='mt-1 w-full rounded border p-2 font-normal' placeholder='Search community…' value={communityFilter} onChange={(e) => setCommunityFilter(e.target.value)} />
        </label>
        <label className='text-sm font-medium text-slate-700'>Filter by location
          <input className='mt-1 w-full rounded border p-2 font-normal' placeholder='Search location…' value={locationFilter} onChange={(e) => setLocationFilter(e.target.value)} />
        </label>
        <div className='flex items-end'>
          <button className='rounded border px-3 py-2 text-sm font-semibold text-slate-700' onClick={() => { setWeekFilterDate(''); setCommunityFilter(''); setLocationFilter(''); }}>Clear Filters</button>
        </div>
      </div>
      <div className='mt-4 flex flex-wrap gap-2'>
        <button className='rounded bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-300' disabled={!canModifyMatrix || !selectedDate} onClick={() => runAction('generate')}>Generate Suggested Host Plan</button>
        <button className='rounded bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-300' disabled={!canModifyMatrix || saving || !Object.keys(dirtyCells).length} onClick={saveChanges}>Save Matrix Changes</button>
        <button className='rounded bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-300' disabled={!canModifyMatrix || !selectedDate} onClick={() => runAction('lock')}>Lock Selected Week</button>
        <button className='rounded border border-blue-300 px-3 py-2 text-sm font-semibold text-blue-700 disabled:text-slate-300' disabled={!canModifyMatrix || !selectedDate} onClick={() => runAction('unlock')}>Unlock Selected Week</button>
        <button className='rounded border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-700 disabled:text-slate-300' disabled={!canModifyMatrix || !selectedDate} onClick={() => runAction('clear')}>Clear Host Plan Selections</button>
        <button className='rounded bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-300' disabled={!canModifyMatrix || !seasonId} onClick={() => runAction('auto')}>Run Auto-Schedule Using Selected Fields</button>
      </div>
      <div className='mt-3 flex flex-wrap gap-3 text-xs text-slate-600'>
        <span><b>Blank</b> = not available</span><span><b>X</b> = available</span><span><b>✓</b> = selected for auto-schedule</span><span><b>O</b> = excluded</span><span><b>P</b> = playoff/championship date</span><span><b>L</b> = locked</span>{canModifyMatrix ? <><span><b>Click</b> = available → selected → excluded</span><span><b>Shift-click</b> = lock/unlock</span><span><b>Right-click</b> = lock, unlock, overflow, or note</span></> : <span><b>Read-only</b> = editing disabled</span>}
      </div>
      {message ? <div className='mt-3 rounded bg-emerald-50 p-2 text-sm text-emerald-800'>{message}</div> : null}
      {error ? <div className='mt-3 rounded bg-rose-50 p-2 text-sm text-rose-800'>{error}</div> : null}
    </div>

    <div className='grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]'>
      <div className='overflow-auto rounded border bg-white shadow-sm'>
        <table className='min-w-full border-collapse text-sm'>
          <thead className='sticky top-0 z-10 bg-slate-100'>
            <tr>
              <th className='sticky left-0 z-20 border-b bg-slate-100 px-3 py-2 text-left'>Community</th>
              <th className='sticky left-36 z-20 border-b bg-slate-100 px-3 py-2 text-left'>Host Location</th>
              {filteredDates.map((date) => <th key={date.game_date} className={`border-b px-2 py-2 text-center ${date.is_postseason ? 'bg-amber-100 font-bold text-amber-900' : ''}`}>
                <button className='min-w-16' onClick={() => setSelectedDate(date.game_date)}>{date.date_type === 'BLACKOUT' ? 'B ' : date.is_postseason ? 'P ' : ''}{formatDate(date.game_date)}</button>
              </th>)}
            </tr>
          </thead>
          <tbody>
            {loading ? <tr><td className='p-4 text-slate-500' colSpan={filteredDates.length + 2}>Loading matrix…</td></tr> : groupedRows.map((group) => group.rows.map((row, index) => <tr key={row.host_location_id} className='border-t'>
              <td className='sticky left-0 bg-white px-3 py-2 font-semibold text-slate-800'>{index === 0 ? group.community : ''}</td>
              <td className='sticky left-36 bg-white px-3 py-2 text-slate-700'>{row.host_location_name}<div className='text-xs text-slate-400'>{row.surface_type}</div></td>
              {filteredDates.map((date) => {
                const cell = getCell(row, date);
                const status = cell.locked ? 'LOCKED' : cell.status;
                const classes = CELL_CLASSES[status] || CELL_CLASSES.AVAILABLE;
                return <td key={date.game_date} className='px-1 py-1 text-center'>
                  <button
                    title={!canModifyMatrix ? HOST_PLAN_SELECTION_PERMISSION_MESSAGE : cell.has_saved_availability ? `${status}${cell.reason ? `: ${cell.reason}` : ''}` : 'Not Available'}
                    className={`h-9 w-12 rounded border text-sm font-semibold ${classes} ${selectedDate === date.game_date ? 'outline outline-2 outline-offset-1 outline-indigo-400' : ''} ${canModifyMatrix ? '' : 'cursor-not-allowed opacity-80'}`}
                    disabled={!canModifyMatrix}
                    onClick={(event) => handleCellClick(row, date, event)}
                    onContextMenu={(event) => handleCellMenu(row, date, event)}
                  >{LABELS[status] ?? status.slice(0, 1)}</button>
                </td>;
              })}
            </tr>))}
            {!loading && !filteredRows.length ? <tr><td className='p-4 text-slate-500' colSpan={filteredDates.length + 2}>No host locations match the current filters.</td></tr> : null}
          </tbody>
        </table>
      </div>

      <aside className='rounded border bg-white p-4 shadow-sm'>
        <h2 className='text-lg font-bold text-slate-900'>Weekly Summary</h2>
        {selectedSummary ? <div className='mt-2 space-y-4 text-sm'>
          <div>
            <div className='font-semibold'>Week {selectedSummary.week_number ?? '—'}, {formatDate(selectedSummary.game_date)}</div>
            <div className='text-slate-500'>{selectedSummary.label} • {(selectedSummary.date_type || 'REGULAR_SEASON').replace('_', ' ')}{selectedSummary.is_postseason ? ' • Playoff/Championship' : ''}</div>
          </div>
          <div className='grid grid-cols-2 gap-2'>
            <div className='rounded bg-slate-50 p-2'><div className='text-xs text-slate-500'>Available communities</div><div className='text-lg font-bold'>{selectedSummaryDetails?.availableCommunities.length ?? selectedSummary.available_communities?.length ?? 0}</div></div>
            <div className='rounded bg-slate-50 p-2'><div className='text-xs text-slate-500'>Available locations</div><div className='text-lg font-bold'>{selectedSummaryDetails?.availableLocations.length ?? selectedSummary.available_locations?.length ?? 0}</div></div>
            <div className='rounded bg-slate-50 p-2'><div className='text-xs text-slate-500'>Selected locations</div><div className='text-lg font-bold'>{visibleSelectedFields.length}</div></div>
            <div className='rounded bg-slate-50 p-2'><div className='text-xs text-slate-500'>Excluded locations</div><div className='text-lg font-bold'>{visibleExcludedFields.length}</div></div>
            <div className='rounded bg-slate-50 p-2'><div className='text-xs text-slate-500'>Total games required</div><div className='text-lg font-bold'>{selectedSummary.total_games_required}</div></div>
            {['SMALL', 'MEDIUM', 'LARGE'].map((size) => <div key={size} className='rounded bg-slate-50 p-2'><div className='text-xs text-slate-500'>{size.charAt(0) + size.slice(1).toLowerCase()} capacity</div><div className='font-bold'>{visibleCapacity[size] || 0}</div></div>)}
          </div>
          <section>
            <h3 className='font-semibold'>Selected</h3>
            <ul className='mt-1 list-disc pl-5 text-slate-700'>{visibleSelectedFields.map((field) => <li key={`${field.community_name}-${field.host_location_name}`}>{field.community_name} / {field.host_location_name}</li>)}{!visibleSelectedFields.length ? <li className='text-slate-400'>No selected fields.</li> : null}</ul>
          </section>
          <section>
            <h3 className='font-semibold'>Excluded available fields</h3>
            <ul className='mt-1 list-disc pl-5 text-slate-700'>{visibleExcludedFields.map((field) => <li key={`${field.community_name}-${field.host_location_name}`}>{field.community_name} / {field.host_location_name}</li>)}{!visibleExcludedFields.length ? <li className='text-slate-400'>None.</li> : null}</ul>
          </section>
          <section>
            <h3 className='font-semibold'>Estimated capacity by field size</h3>
            <div className='mt-1 grid grid-cols-3 gap-2'>{['SMALL', 'MEDIUM', 'LARGE'].map((size) => <div key={size} className='rounded border p-2 text-center'><div className='text-xs text-slate-500'>{size}</div><div className='font-bold'>{visibleCapacity[size] || 0}</div></div>)}</div>
          </section>
          <section>
            <h3 className='font-semibold'>Expected host communities</h3>
            <ul className='mt-1 list-disc pl-5 text-slate-700'>{(selectedSummaryDetails?.expectedHostCommunities || selectedSummary.expected_host_communities || selectedSummary.selected_communities).map((community) => <li key={community}>{community}</li>)}{!(selectedSummaryDetails?.expectedHostCommunities || selectedSummary.expected_host_communities || selectedSummary.selected_communities).length ? <li className='text-slate-400'>No expected host communities.</li> : null}</ul>
          </section>
          <section>
            <h3 className='font-semibold'>Target game split</h3>
            <ul className='mt-1 list-disc pl-5'>{Object.entries(selectedSummary.target_game_split).map(([community, games]) => <li key={community}>{community}: {games} games</li>)}{!Object.keys(selectedSummary.target_game_split).length ? <li className='text-slate-400'>Select fields to calculate split.</li> : null}</ul>
          </section>
          {selectedSummary.weekly_host_plan_decision_summary ? <section>
            <h3 className='font-semibold'>Weekly Host Plan Decision Summary</h3>
            <dl className='mt-1 space-y-1 text-slate-700'>
              <div><dt className='inline font-medium'>Selected communities:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.selected_communities.join(', ') || '—'}</dd></div>
              <div><dt className='inline font-medium'>Excluded communities:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.excluded_communities.join(', ') || '—'}</dd></div>
              <div><dt className='inline font-medium'>Total games required:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.total_games_required}</dd></div>
              <div><dt className='inline font-medium'>Selected total capacity:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.selected_total_capacity}</dd></div>
              <div><dt className='inline font-medium'>Selected Small / Medium / Large capacity:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.selected_small_capacity} / {selectedSummary.weekly_host_plan_decision_summary.selected_medium_capacity} / {selectedSummary.weekly_host_plan_decision_summary.selected_large_capacity}</dd></div>
              <div><dt className='inline font-medium'>Doubleheader adjacency available:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.doubleheader_adjacency_available ? 'yes' : 'no'}</dd></div>
              <div><dt className='inline font-medium'>Home-field requirement satisfied:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.home_field_requirement_satisfied ? 'yes' : 'no'}</dd></div>
              <div><dt className='inline font-medium'>Additional host needed:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.additional_host_needed ? 'yes' : 'no'}</dd></div>
              <div><dt className='inline font-medium'>Reason additional host was added:</dt> <dd className='inline'>{selectedSummary.weekly_host_plan_decision_summary.reason_additional_host_was_added || '—'}</dd></div>
            </dl>
          </section> : null}
          <section>
            <h3 className='font-semibold'>Validation</h3>
            {selectedSummary.validation_warnings.length ? <ul className='mt-1 list-disc pl-5 text-rose-700'>{selectedSummary.validation_warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : <p className='mt-1 text-emerald-700'>Selected capacity supports the estimated week demand.</p>}
            <p className='mt-2 text-xs text-slate-500'>Odd-team doubleheader adjacency is enforced by the auto-scheduler; add an overflow field if adjacent same-location slots are unavailable.</p>
          </section>
        </div> : <p className='mt-2 text-sm text-slate-500'>Select a date column to view capacity, selected fields, excluded fields, and validation.</p>}
      </aside>
    </div>
  </div>;
}
