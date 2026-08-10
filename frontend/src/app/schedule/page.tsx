'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { API_URL } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';
import Link from 'next/link';
import CommunityLogo from '@/components/CommunityLogo';
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
  home_team_community_id?: string | null;
  home_team_community_name?: string | null;
  home_team_logo_url?: string | null;
  home_team_logo_alt_text?: string | null;
  away_team_name: string;
  away_team_community_id?: string | null;
  away_team_community_name?: string | null;
  away_team_logo_url?: string | null;
  away_team_logo_alt_text?: string | null;
  game_type: string;
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
    const token = getToken();
    const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined;
    const [gamesRes, optionsRes] = await Promise.all([
      fetch(`${API_URL}/public/schedule?${q.toString()}`, { headers: authHeaders }),
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
    <div className='mx-auto w-[96%] max-w-[1600px] space-y-5 px-6 py-5'>
      <div className='flex flex-wrap items-start justify-between gap-3'><div><h1 className='text-[26px] font-bold leading-tight'>{APP_SCHEDULE_NAME}</h1><p className='mt-1 text-base font-medium text-slate-600'>{APP_SUBTITLE}</p></div><div className='flex flex-wrap gap-2'><Link className='inline-flex h-11 items-center rounded border px-4 text-[15px] font-medium hover:bg-slate-50' href='/tournaments'>Tournament Bracket</Link><Link className='inline-flex h-11 items-center rounded border px-4 text-[15px] font-medium hover:bg-slate-50' href='/rulebook'>Rulebook</Link></div></div>

      <div className='grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5'>
        <select className='h-11 rounded border px-3 text-base' value={filters.host_location_id || ''} onChange={(e) => setFilters({ ...filters, host_location_id: e.target.value })}>
          <option value=''>All Host Locations</option>
          {options.host_locations.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select className='h-11 rounded border px-3 text-base' value={filters.organization_id || ''} onChange={(e) => setFilters({ ...filters, organization_id: e.target.value })}>
          <option value=''>All Communities</option>
          {options.organizations.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select className='h-11 rounded border px-3 text-base' value={filters.division_id || ''} onChange={(e) => setFilters({ ...filters, division_id: e.target.value })}>
          <option value=''>All Divisions</option>
          {options.divisions.map((o: any) => <option key={o.id} value={o.id}>{getDivisionLabel(o)}</option>)}
        </select>
        <select className='h-11 rounded border px-3 text-base' value={filters.week_id || ''} onChange={(e) => setFilters({ ...filters, week_id: e.target.value })}>
          <option value=''>All Weeks</option>
          {options.weeks.map((o: any) => <option key={o.id} value={o.id}>{getWeekOptionLabel(o)}</option>)}
        </select>
        <select className='h-11 rounded border px-3 text-base' value={filters.team_id || ''} onChange={(e) => setFilters({ ...filters, team_id: e.target.value })}>
          <option value=''>All Teams</option>
          {options.teams.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      </div>

      <div className='flex flex-wrap gap-2'>
        <button className='h-11 rounded bg-slate-800 px-4 text-[15px] font-medium text-white' onClick={() => load(filters)}>Apply Filters</button>
        <button className='h-11 rounded border px-4 text-[15px] font-medium' onClick={() => { setFilters({}); load({}); }}>Reset</button>
        <button className='h-11 rounded border px-4 text-[15px] font-medium' onClick={() => window.print()}>Print / PDF</button>
      </div>

      {loading && <div className='rounded border p-4'>Loading saved schedule...</div>}
      {empty && <div className='rounded border p-4'>{message || (hasActiveFilters ? 'No games match the selected filters.' : 'No saved schedule is currently available.')}</div>}
      {!loading && games.length > 0 && (
        <div className='overflow-x-auto rounded border'>
          <table className='w-full min-w-[1180px] table-fixed text-[15px] leading-snug'>
            <colgroup>
              <col className='w-[10%]' />
              <col className='w-[8%]' />
              <col className='w-[13%]' />
              <col className='w-[14%]' />
              <col className='w-[8%]' />
              <col className='w-[19%]' />
              <col className='w-[19%]' />
              <col className='w-[9%]' />
            </colgroup>
            <thead className='bg-slate-100 text-left text-[15px] font-semibold'>
              <tr>
                <th className='whitespace-nowrap px-3 py-3'>Date</th>
                <th className='whitespace-nowrap px-3 py-3'>Time</th>
                <th className='whitespace-nowrap px-3 py-3'>Host Location</th>
                <th className='whitespace-nowrap px-3 py-3'>Field</th>
                <th className='whitespace-nowrap px-3 py-3'>Division</th>
                <th className='px-3 py-3'>Home Team</th>
                <th className='px-3 py-3'>Away Team</th>
                <th className='whitespace-nowrap px-3 py-3'>Game Type</th>
              </tr>
            </thead>
            <tbody>
              {games.map((g) => (
                <tr key={g.id} className='border-t'>
                  <td className='whitespace-nowrap px-3 py-3'>{formatDisplayDate(g.game_date)}</td>
                  <td className='whitespace-nowrap px-3 py-3'>{formatDisplayTime(g.kickoff_time)}</td>
                  <td className='whitespace-nowrap px-3 py-3'>{g.host_location_name}</td>
                  <td className='whitespace-nowrap px-3 py-3'>{g.field_name}</td>
                  <td className='whitespace-nowrap px-3 py-3'>{g.division_name}</td>
                  <td className='px-3 py-3'><span className='flex items-center gap-2'><CommunityLogo src={g.home_team_logo_url} name={g.home_team_community_name || g.home_team_name} altText={g.home_team_logo_alt_text} size={24} />{g.home_team_name}</span></td>
                  <td className='px-3 py-3'><span className='flex items-center gap-2'><CommunityLogo src={g.away_team_logo_url} name={g.away_team_community_name || g.away_team_name} altText={g.away_team_logo_alt_text} size={24} />{g.away_team_name}</span></td>
                  <td className='whitespace-nowrap px-3 py-3'>{g.game_type === 'REGULAR_SEASON' ? 'Regular Season' : g.game_type.replaceAll('_', ' ')}</td>
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
    <Suspense fallback={<div className='mx-auto w-[96%] max-w-[1600px] px-6 py-5 text-base'>Loading saved schedule...</div>}>
      <PublicScheduleContent />
    </Suspense>
  );
}
