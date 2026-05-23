'use client';

import { useEffect, useMemo, useState } from 'react';
import { API_URL, ApiError, apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';

const tabs = ['By Date', 'By Host Location', 'By Team', 'By Division'] as const;
type TabKey = (typeof tabs)[number];

export default function ScheduleManagementPage() {
  const token = getToken();
  const [tab, setTab] = useState<TabKey>('By Date');
  const [options, setOptions] = useState<any>({
    divisions: [],
    teams: [],
    host_locations: [],
    organizations: [],
    fields: [],
  });
  const [filters, setFilters] = useState<any>({
    date: '',
    division_id: '',
    organization_id: '',
    host_location_id: '',
    field_id: '',
    team_id: '',
  });
  const [games, setGames] = useState<any[]>([]);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [quality, setQuality] = useState<any | null>(null);
  const [error, setError] = useState('');

  const qs = useMemo(
    () =>
      Object.entries(filters)
        .filter(([, value]) => value)
        .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
        .join('&'),
    [filters]
  );

  const load = async () => {
    const opts: any = await apiFetch('/manual-schedule-builder/options', {}, token);
    const orgs: any = await apiFetch('/organizations?page_size=500', {}, token);
    setOptions({
      ...opts,
      organizations: orgs.items || [],
      fields: opts.fields || [],
    });

    const gameResponse: any = await apiFetch(`/schedule-management/games${qs ? `?${qs}` : ''}`, {}, token);
    const conflictResponse: any = await apiFetch('/schedule-management/conflicts', {}, token);
    const qualityResponse: any = await apiFetch(`/schedule-management/quality-report${qs ? `?${qs}` : ''}`, {}, token);

    setGames(gameResponse.items || []);
    setConflicts(conflictResponse.conflicts || []);
    setQuality(qualityResponse || null);
  };

  useEffect(() => {
    load().catch((e) => {
      setError(e instanceof ApiError ? e.message : 'Unable to load schedule management data.');
    });
  }, [qs]);



  const exportCsv = async () => {
    try {
      const response = await fetch(`${API_URL}/schedule-management/export.csv${qs ? `?${qs}` : ''}`, {
        method: 'GET',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          Accept: 'text/csv',
        },
      });

      if (!response.ok) {
        throw new ApiError('Unable to export CSV.', response.status, await response.text());
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'schedule-export.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Unable to export schedule CSV.');
    }
  };



  const statusClass = (status: string) => {
    if (status === 'OK') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Warning') return 'bg-amber-100 text-amber-700';
    return 'bg-red-100 text-red-700';
  };

  const grouped = useMemo(() => {
    const by: Record<string, any[]> = {};

    for (const game of games) {
      const groupKey =
        tab === 'By Date'
          ? game.date || 'No Date'
          : tab === 'By Host Location'
            ? game.host_location_name || 'Unassigned Host Location'
            : tab === 'By Team'
              ? `${game.home_team_name || 'Unknown'} vs ${game.away_team_name || 'Unknown'}`
              : game.division_name || 'Unknown Division';

      if (!by[groupKey]) by[groupKey] = [];
      by[groupKey].push(game);
    }

    return Object.entries(by);
  }, [games, tab]);

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Schedule Management</h1>

      {error ? <div className='rounded border border-red-300 bg-red-50 p-2 text-red-700'>{error}</div> : null}

      <div className='grid gap-2 md:grid-cols-6'>
        <input
          type='date'
          className='rounded border p-2'
          value={filters.date}
          onChange={(e) => setFilters({ ...filters, date: e.target.value })}
          aria-label='Date'
        />

        <select
          className='rounded border p-2'
          value={filters.division_id}
          onChange={(e) => setFilters({ ...filters, division_id: e.target.value })}
        >
          <option value=''>Division</option>
          {options.divisions.map((division: any) => (
            <option key={division.id} value={division.id}>
              {getDivisionLabel(division)}
            </option>
          ))}
        </select>

        <select
          className='rounded border p-2'
          value={filters.organization_id}
          onChange={(e) => setFilters({ ...filters, organization_id: e.target.value })}
        >
          <option value=''>Organization</option>
          {options.organizations.map((organization: any) => (
            <option key={organization.id} value={organization.id}>
              {organization.name}
            </option>
          ))}
        </select>

        <select
          className='rounded border p-2'
          value={filters.host_location_id}
          onChange={(e) => setFilters({ ...filters, host_location_id: e.target.value })}
        >
          <option value=''>Host Location</option>
          {options.host_locations.map((hostLocation: any) => (
            <option key={hostLocation.id} value={hostLocation.id}>
              {hostLocation.name}
            </option>
          ))}
        </select>

        <select
          className='rounded border p-2'
          value={filters.field_id}
          onChange={(e) => setFilters({ ...filters, field_id: e.target.value })}
        >
          <option value=''>Field</option>
          {options.fields.map((field: any) => (
            <option key={field.id} value={field.id}>
              {field.name}
            </option>
          ))}
        </select>

        <select
          className='rounded border p-2'
          value={filters.team_id}
          onChange={(e) => setFilters({ ...filters, team_id: e.target.value })}
        >
          <option value=''>Team</option>
          {options.teams.map((team: any) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </select>
      </div>

      <div className='flex flex-wrap gap-2'>
        {tabs.map((tabName) => (
          <button
            key={tabName}
            onClick={() => setTab(tabName)}
            className={`rounded px-3 py-1 ${tab === tabName ? 'bg-blue-600 text-white' : 'bg-slate-200'}`}
          >
            {tabName}
          </button>
        ))}
      </div>

      <button className='inline-block rounded bg-emerald-600 px-3 py-2 text-white' onClick={exportCsv}>
        Export CSV
      </button>

      <div className='rounded border p-3'>
        <h2 className='mb-2 font-semibold'>Schedule Conflicts</h2>
        {conflicts.length === 0 ? (
          <p>No schedule conflicts found.</p>
        ) : (
          <ul className='list-disc pl-6'>
            {conflicts.map((conflict: any, index: number) => (
              <li key={index}>{conflict.message}</li>
            ))}
          </ul>
        )}
      </div>



      <div className='space-y-4 rounded border p-3'>
        <h2 className='text-xl font-semibold'>Schedule Quality Report</h2>
        {!quality ? <p>Loading quality report...</p> : (
          <>
            <section>
              <h3 className='font-semibold'>Games Per Team</h3>
              {quality.games_per_team?.map((row: any) => <div key={row.team_id} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.team_name} ({row.division_name}) - {row.games_scheduled} games (avg {row.division_average})</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>)}
            </section>
            <section>
              <h3 className='font-semibold'>Repeat Matchups</h3>
              {quality.repeat_matchups?.length ? quality.repeat_matchups.map((row: any, i: number) => <div key={i} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.team_a} vs {row.team_b}: {row.games} times</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>) : <p className='text-sm'>None found.</p>}
            </section>
            <section>
              <h3 className='font-semibold'>Home/Away Balance</h3>
              {quality.home_away_balance?.map((row: any, i: number) => <div key={i} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.team_name}: H {row.home_games} / A {row.away_games} (variance {row.variance})</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>)}
            </section>
            <section>
              <h3 className='font-semibold'>Time-of-Day Balance</h3>
              {quality.time_of_day_balance?.map((row: any, i: number) => <div key={i} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.team_name}: Morning {row.morning}, Midday {row.midday}, Afternoon {row.afternoon}</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>)}
            </section>
            <section>
              <h3 className='font-semibold'>Host Community Priority</h3>
              {quality.host_community_priority?.map((row: any, i: number) => <div key={i} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.organization_name}: {row.games_when_community_hosts} games, {row.home_percentage_during_host_dates}% home</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>)}
            </section>
            <section>
              <h3 className='font-semibold'>Double Headers</h3>
              {quality.double_headers?.length ? quality.double_headers.map((row: any, i: number) => <div key={i} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.team_name} on {row.date}: {row.games} games ({row.is_back_to_back ? 'Back-to-back' : 'Not back-to-back'})</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>) : <p className='text-sm'>None found.</p>}
            </section>
            <section>
              <h3 className='font-semibold'>Unscheduled Teams</h3>
              {quality.unscheduled_teams?.length ? quality.unscheduled_teams.map((row: any, i: number) => <div key={i} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.team_name} ({row.division_name})</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>) : <p className='text-sm'>None found.</p>}
            </section>
            <section>
              <h3 className='font-semibold'>Field Utilization</h3>
              {quality.field_utilization?.map((row: any, i: number) => <div key={i} className='flex items-center justify-between border-b py-1 text-sm'><span>{row.host_location_name} {row.date}: open {row.open_slots}, assigned {row.assigned_slots}, {row.utilization_percent}%</span><span className={`rounded px-2 py-0.5 ${statusClass(row.status)}`}>{row.status}</span></div>)}
            </section>
          </>
        )}
      </div>

      <div className='space-y-3'>
        {grouped.map(([groupName, groupGames]) => (
          <div key={groupName} className='rounded border p-3'>
            <h3 className='mb-2 text-lg font-semibold'>{groupName}</h3>

            {(groupGames as any[]).map((game) => (
              <div key={game.id} className='mb-2 rounded border p-2'>
                <div><strong>Date:</strong> {game.date || 'N/A'}</div>
                <div><strong>Host Location:</strong> {game.host_location_name || 'Unassigned'}</div>
                <div><strong>Field:</strong> {game.field || 'Unassigned'}</div>
                <div><strong>Time:</strong> {game.time || 'N/A'}</div>
                <div>
                  <strong>Matchup:</strong> {game.home_team_name || 'TBD'} vs {game.away_team_name || 'TBD'}
                </div>
                <div><strong>Division:</strong> {game.division_name || 'N/A'}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
