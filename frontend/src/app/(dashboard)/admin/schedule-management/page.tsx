'use client';

import { useEffect, useMemo, useState } from 'react';
import { API_URL, ApiError, apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

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

    setGames(gameResponse.items || []);
    setConflicts(conflictResponse.conflicts || []);
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
              {division.name}
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
