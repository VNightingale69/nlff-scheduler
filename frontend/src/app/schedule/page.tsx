'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { API_URL } from '@/lib/api';
import { getDivisionLabel } from '@/lib/divisionLabel';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';
import Link from 'next/link';
import { APP_SCHEDULE_NAME, APP_SUBTITLE } from '@/config/branding';

type Game = {
  id: string;
  game_date: string;
  kickoff_time: string;
  host_location_name: string;
  field_name: string;
  turf_configuration_code?: string | null;
  turf_field_slot?: string | null;
  division_name: string;
  home_team_name: string;
  away_team_name: string;
  game_status_label: string;
  public_score_status?: string | null;
  home_score?: number | null;
  away_score?: number | null;
  week_label?: string | null;
  date_type?: string | null;
};

type PublicScheduleFilters = {
  host_location_id?: string;
  organization_id?: string;
  division_id?: string;
  week_id?: string;
  team_id?: string;
};

type PublicScheduleOptions = {
  host_locations: any[];
  organizations: any[];
  divisions: any[];
  weeks: any[];
  teams: any[];
};

const PUBLIC_FILTER_KEYS: Array<keyof PublicScheduleFilters> = [
  'host_location_id',
  'organization_id',
  'division_id',
  'week_id',
  'team_id',
];

const emptyOptions: PublicScheduleOptions = {
  host_locations: [],
  organizations: [],
  divisions: [],
  weeks: [],
  teams: [],
};

const getWeekOptionLabel = (week: any) => {
  const baseLabel = week.label || `Week ${week.week_number}`;
  const dateTypeLabel = week.date_type && week.date_type !== 'REGULAR_SEASON' ? ` (${week.date_type.replace('_', ' ')})` : '';
  if (!week.start_date) return `${baseLabel}${dateTypeLabel}`;
  const formattedDate = formatDisplayDate(week.start_date);
  return `${baseLabel}${dateTypeLabel} — ${formattedDate}`;
};

const buildScheduleQuery = (activeFilters: PublicScheduleFilters) => {
  const query = new URLSearchParams({ page_size: '1000' });

  PUBLIC_FILTER_KEYS.forEach((key) => {
    const value = activeFilters[key];
    if (value) query.set(key, value);
  });

  return query;
};

function PublicScheduleContent() {
  const searchParams = useSearchParams();
  const [games, setGames] = useState<Game[]>([]);
  const [filters, setFilters] = useState<PublicScheduleFilters>({ week_id: searchParams.get('week_id') || undefined });
  const [options, setOptions] = useState<PublicScheduleOptions>(emptyOptions);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  const load = async (activeFilters: PublicScheduleFilters = filters) => {
    setLoading(true);
    const q = buildScheduleQuery(activeFilters);
    const [gamesRes, optionsRes] = await Promise.all([
      fetch(`${API_URL}/public/schedule?${q.toString()}`),
      fetch(`${API_URL}/public/schedule/options`),
    ]);
    const gamesPayload = await gamesRes.json();
    setGames(gamesPayload.items || []);
    setMessage(gamesPayload.message || '');
    setOptions(await optionsRes.json());
    setLoading(false);
  };

  useEffect(() => {
    load({});
  }, []);

  const empty = useMemo(() => !loading && games.length === 0, [loading, games.length]);
  const hasActiveFilters = useMemo(() => Object.values(filters).some(Boolean), [filters]);

  return (
    <div className='mx-auto max-w-6xl space-y-4 p-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'><div><h1 className='text-2xl font-bold'>{APP_SCHEDULE_NAME}</h1><p className='mt-1 text-sm font-medium text-slate-600'>{APP_SUBTITLE}</p></div><Link className='rounded border px-3 py-2 text-sm hover:bg-slate-50' href='/rulebook'>Rulebook</Link></div>

      <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5'>
        <select className='rounded border p-2' value={filters.host_location_id || ''} onChange={(e) => setFilters({ ...filters, host_location_id: e.target.value })}>
          <option value=''>All Host Locations</option>
          {options.host_locations.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select className='rounded border p-2' value={filters.organization_id || ''} onChange={(e) => setFilters({ ...filters, organization_id: e.target.value })}>
          <option value=''>All Communities</option>
          {options.organizations.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select className='rounded border p-2' value={filters.division_id || ''} onChange={(e) => setFilters({ ...filters, division_id: e.target.value })}>
          <option value=''>All Divisions</option>
          {options.divisions.map((o: any) => <option key={o.id} value={o.id}>{getDivisionLabel(o)}</option>)}
        </select>
        <select className='rounded border p-2' value={filters.week_id || ''} onChange={(e) => setFilters({ ...filters, week_id: e.target.value })}>
          <option value=''>All Weeks</option>
          {options.weeks.map((o: any) => <option key={o.id} value={o.id}>{getWeekOptionLabel(o)}</option>)}
        </select>
        <select className='rounded border p-2' value={filters.team_id || ''} onChange={(e) => setFilters({ ...filters, team_id: e.target.value })}>
          <option value=''>All Teams</option>
          {options.teams.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </div>

      <div className='flex flex-wrap gap-2'>
        <button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={() => load(filters)}>Apply Filters</button>
        <button className='rounded border px-3 py-2' onClick={() => { setFilters({}); load({}); }}>Reset</button>
        <button className='rounded border px-3 py-2' onClick={() => window.print()}>Print / PDF</button>
      </div>

      {loading && <div className='rounded border p-4'>Loading published schedule...</div>}
      {empty && <div className='rounded border p-4'>{message || (hasActiveFilters ? 'No games match the selected filters.' : 'No published schedule is currently available.')}</div>}
      {!loading && games.length > 0 && (
        <div className='overflow-x-auto rounded border'>
          <table className='min-w-full text-sm'>
            <thead className='bg-slate-100 text-left'>
              <tr>
                <th className='p-2'>Date</th>
                <th className='p-2'>Time</th>
                <th className='p-2'>Host location</th>
                <th className='p-2'>Field</th>
                <th className='p-2'>Division</th>
                <th className='p-2'>Home team</th>
                <th className='p-2'>Away team</th>
                <th className='p-2'>Game type</th>
                <th className='p-2'>Game status</th>
                <th className='p-2'>Score</th>
              </tr>
            </thead>
            <tbody>
              {games.map((g) => (
                <tr key={g.id} className='border-t'>
                  <td className='p-2'>{formatDisplayDate(g.game_date)}</td>
                  <td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td>
                  <td className='p-2'>{g.host_location_name}</td>
                  <td className='p-2'>
                    <div>{g.field_name}</div>
                    {g.turf_configuration_code && (
                      <div className='text-xs text-slate-500'>
                        {g.turf_configuration_code} · {g.turf_field_slot || 'Turf slot'}
                      </div>
                    )}
                  </td>
                  <td className='p-2'>{g.division_name}</td>
                  <td className='p-2'>{g.home_team_name}</td>
                  <td className='p-2'>{g.away_team_name}</td>
                  <td className='p-2'>{g.date_type === 'PLAYOFF' ? 'PLAYOFF' : g.week_label || 'Regular Season'}</td>
                  <td className='p-2'>{g.game_status_label}</td>
                  <td className='p-2'>{g.public_score_status === 'APPROVED' ? `${g.home_team_name} ${g.home_score}, ${g.away_team_name} ${g.away_score}` : g.public_score_status === 'SCORE_PENDING' ? 'Score Pending' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function PublicSchedulePage() {
  return (
    <Suspense fallback={<div className='mx-auto max-w-6xl p-4'>Loading published schedule...</div>}>
      <PublicScheduleContent />
    </Suspense>
  );
}
