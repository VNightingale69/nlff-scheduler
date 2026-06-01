'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

const initialForm = { season_id: '', week_id: '', division_id: '', home_team_id: '', away_team_id: '', field_id: '', game_status_id: '', game_date: '', kickoff_time: '' };
const emptyFilters = { division_id: '', week_id: '', team_id: '', host_location_id: '', status_code: '' };

const getWeekOptionLabel = (week: any) => {
  const baseLabel = week.label || `Week ${week.week_number}`;
  const date = week.primary_game_date || week.start_date;
  return date ? `${baseLabel} — ${formatDisplayDate(date)}` : baseLabel;
};

const getStatusLabel = (statusLabels: Record<string, string>, statusCode: string) => {
  if (statusLabels[statusCode]) return statusLabels[statusCode];
  return statusCode
    ? statusCode.replace(/_/g, ' ').toLowerCase().replace(/(^|\s)\S/g, (letter) => letter.toUpperCase())
    : '';
};

const filterSelects = [
  { key: 'division_id', label: 'Division / Grade Level', allLabel: 'All' },
  { key: 'week_id', label: 'Game Week', allLabel: 'All' },
  { key: 'team_id', label: 'Team', allLabel: 'All' },
  { key: 'host_location_id', label: 'Host Location', allLabel: 'All' },
  { key: 'status_code', label: 'Schedule Status', allLabel: 'All' },
] as const;

const formSelectLabels: Record<string, string> = {
  season_id: 'Season',
  week_id: 'Game Week',
  division_id: 'Division / Grade Level',
  home_team_id: 'Home Team',
  away_team_id: 'Away Team',
  field_id: 'Field',
  game_status_id: 'Schedule Status',
};

export default function GamesPage() {
  const user = getAuthUser();
  const isCommunityAdmin = user?.role_name === 'COMMUNITY_ADMIN';
  const [games, setGames] = useState<any[]>([]);
  const [form, setForm] = useState<any>(initialForm);
  const [editingId, setEditingId] = useState<string | undefined>();
  const [validation, setValidation] = useState<any>();
  const [filters, setFilters] = useState<Record<string, string>>(emptyFilters);
  const [refs, setRefs] = useState<any>({ seasons: [], weeks: [], divisions: [], teams: [], fields: [], hostLocations: [], statuses: [] });

  const statusLabels = useMemo(
    () => Object.fromEntries((refs.statuses || []).map((status: any) => [status.code, status.label])),
    [refs.statuses]
  );

  const filterOptions = useMemo(() => ({
    division_id: (refs.divisions || []).map((division: any) => ({ value: division.id, label: getDivisionLabel(division) })),
    week_id: (refs.weeks || []).map((week: any) => ({ value: week.id, label: getWeekOptionLabel(week) })),
    team_id: (refs.teams || []).map((team: any) => ({ value: team.id, label: team.name })),
    host_location_id: (refs.hostLocations || []).map((hostLocation: any) => ({ value: hostLocation.id, label: hostLocation.name })),
    status_code: (refs.statuses || []).map((status: any) => ({ value: status.code, label: status.label })),
  }), [refs]);

  const loadRefs = async () => {
    const token = getToken();
    const [seasons, weeks, divisions, teams, fields, hostLocations, statuses] = await Promise.all([
      apiFetch('/seasons?page_size=1000', {}, token),
      apiFetch('/weeks?page_size=1000', {}, token),
      apiFetch('/divisions?page_size=1000', {}, token),
      apiFetch('/teams?page_size=1000', {}, token),
      apiFetch('/fields?page_size=1000', {}, token),
      apiFetch('/host-locations?page_size=1000', {}, token),
      apiFetch('/game-statuses?page_size=1000', {}, token),
    ]);
    setRefs({
      seasons: seasons.items || [],
      weeks: weeks.items || [],
      divisions: divisions.items || [],
      teams: teams.items || [],
      fields: fields.items || [],
      hostLocations: hostLocations.items || [],
      statuses: statuses.items || [],
    });
  };

  const loadGames = async (activeFilters = filters) => {
    const params = Object.fromEntries(Object.entries(activeFilters).filter(([, value]) => Boolean(value))) as Record<string, string>;
    const query = new URLSearchParams(params);
    const data = await apiFetch(`/games?${query.toString()}`, {}, getToken());
    setGames(data.items || []);
  };

  useEffect(() => {
    loadRefs();
    loadGames(emptyFilters);
  }, []);

  const save = async () => {
    const path = editingId ? `/games/${editingId}` : '/games';
    const method = editingId ? 'PUT' : 'POST';
    try {
      const res = await apiFetch(path, { method, body: JSON.stringify(form) }, getToken());
      setValidation(res.validation);
      setForm(initialForm);
      setEditingId(undefined);
      loadGames();
    } catch (e: any) {
      setValidation({ hard_conflicts: [{ code: 'save_error', message: e.message }], soft_warnings: [] });
    }
  };

  const clearFilters = () => {
    setFilters(emptyFilters);
    loadGames(emptyFilters);
  };

  return <div className='space-y-4'>
    <h1 className='text-2xl font-bold'>{isCommunityAdmin ? 'League Schedule' : 'Manual Game Schedule Builder'}</h1>

    <div className='rounded border p-3'>
      <h2 className='mb-3 text-lg font-semibold'>Schedule Filters</h2>
      <div className='grid gap-3 md:grid-cols-5'>
        {filterSelects.map((filter) => (
          <label key={filter.key} className='space-y-1 text-sm font-medium text-slate-700'>
            <span>{filter.label}</span>
            <select
              className='w-full rounded border p-2 font-normal text-slate-900'
              value={filters[filter.key] || ''}
              onChange={(event) => setFilters({ ...filters, [filter.key]: event.target.value })}
            >
              <option value=''>{filter.allLabel}</option>
              {filterOptions[filter.key].map((option: any) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
        ))}
      </div>
      <div className='mt-3 flex flex-wrap gap-2'>
        <button className='rounded bg-slate-700 px-3 py-2 text-white' onClick={() => loadGames(filters)}>Apply Filters</button>
        <button className='rounded border px-3 py-2' onClick={clearFilters}>Clear Filters</button>
      </div>
    </div>

    {!isCommunityAdmin && <div className='grid gap-2 rounded border p-3 md:grid-cols-2'>
      <input type='date' className='rounded border p-2' value={form.game_date} onChange={e => setForm({ ...form, game_date: e.target.value })} />
      <input type='time' className='rounded border p-2' value={form.kickoff_time} onChange={e => setForm({ ...form, kickoff_time: e.target.value })} />
      {[
        ['season_id', refs.seasons, 'name'],
        ['week_id', refs.weeks, getWeekOptionLabel],
        ['division_id', refs.divisions, getDivisionLabel],
        ['home_team_id', refs.teams, 'name'],
        ['away_team_id', refs.teams, 'name'],
        ['field_id', refs.fields, 'name'],
        ['game_status_id', refs.statuses, 'label'],
      ].map(([key, list, label]) => <select key={key as string} className='rounded border p-2' value={form[key as string]} onChange={e => setForm({ ...form, [key as string]: e.target.value })}>
        <option value=''>{formSelectLabels[key as string]}</option>
        {(list as any[]).map(option => <option key={option.id} value={option.id}>{typeof label === 'function' ? label(option) : option[label as string]}</option>)}
      </select>)}
      <div className='md:col-span-2 flex gap-2'><button className='rounded bg-emerald-700 px-4 py-2 text-white' onClick={save}>{editingId ? 'Update' : 'Create'}</button></div>
    </div>}

    {validation && <div className='rounded border p-3'><h2 className='font-semibold'>Validation results</h2><p>Hard conflicts: {validation.hard_conflicts?.length || 0}</p><ul>{validation.hard_conflicts?.map((x: any) => <li key={x.code}>• {x.message}</li>)}</ul><p>Soft warnings: {validation.soft_warnings?.length || 0}</p></div>}
    <div className='overflow-x-auto rounded border'><table className='w-full text-sm'><thead><tr><th>Date</th><th>Time</th><th>Status</th><th /></tr></thead><tbody>{games.map(g => <tr key={g.id}><td>{formatDisplayDate(g.game_date)}</td><td>{formatDisplayTime(g.kickoff_time)}</td><td>{getStatusLabel(statusLabels, g.status_code)}</td><td>{!isCommunityAdmin && <button className='underline' onClick={() => { setForm(g); setEditingId(g.id); }}>Edit</button>}</td></tr>)}</tbody></table></div>
  </div>;
}
