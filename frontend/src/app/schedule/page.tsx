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
  field_type?: string | null;
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

type ScheduleView = 'list' | 'hosting';
type HostingField = { key: string; name: string; type: string };
type HostingLocation = { name: string; fields: HostingField[] };

const normalizeFieldType = (value?: string | null) => {
  const normalized = (value || '').toUpperCase();
  if (normalized.includes('SMALL') || normalized.includes('THIRTY')) return 'SMALL';
  if (normalized.includes('MEDIUM') || normalized.includes('FIFTY')) return 'MEDIUM';
  if (normalized.includes('LARGE') || normalized.includes('FULL')) return 'LARGE';
  return 'UNASSIGNED';
};

const fieldTypeLabel = (type: string) => type === 'UNASSIGNED' ? 'Unassigned' : `${type[0]}${type.slice(1).toLowerCase()} Field`;
const fieldTone = (type: string) => ({
  SMALL: 'bg-emerald-50',
  MEDIUM: 'bg-sky-50',
  LARGE: 'bg-rose-50',
  UNASSIGNED: 'bg-slate-50',
}[type] || 'bg-slate-50');

const locationAccent = (index: number) => `location-accent-${(index % 4) + 1}`;
const locationEdge = (fieldIndex: number, fieldCount: number) => [
  fieldIndex === 0 ? 'location-boundary-start' : '',
  fieldIndex === fieldCount - 1 ? 'location-boundary-end' : '',
].filter(Boolean).join(' ');

const gameField = (game: Game): HostingField => {
  const assignedName = game.turf_field_slot || (game.field_name && !/not assigned|unavailable/i.test(game.field_name) ? game.field_name : 'Unassigned');
  const type = assignedName === 'Unassigned' ? 'UNASSIGNED' : normalizeFieldType(game.field_type || assignedName);
  return { key: assignedName, name: assignedName, type };
};

function HostingSchedule({ games }: { games: Game[] }) {
  const dates = useMemo(() => Array.from(new Set(games.map((game) => game.game_date))).sort(), [games]);

  return <div className='hosting-view space-y-10'>
    <div className='flex flex-wrap items-center gap-3 text-sm' aria-label='Field size legend'>
      <span className='font-semibold text-slate-700'>Field legend:</span>
      {['SMALL', 'MEDIUM', 'LARGE', 'UNASSIGNED'].map((type) => <span key={type} className={`rounded border px-3 py-1.5 ${fieldTone(type)}`}>{type === 'UNASSIGNED' ? 'No Game / Unassigned' : fieldTypeLabel(type)}</span>)}
    </div>
    {dates.map((date) => {
      const dateGames = games.filter((game) => game.game_date === date);
      const locations: HostingLocation[] = [];
      dateGames.forEach((game) => {
        const locationName = game.host_location_name || 'Host Location Unassigned';
        let location = locations.find((item) => item.name === locationName);
        if (!location) { location = { name: locationName, fields: [] }; locations.push(location); }
        const field = gameField(game);
        if (!location.fields.some((item) => item.key === field.key)) location.fields.push(field);
      });
      const times = Array.from(new Set(dateGames.map((game) => game.kickoff_time))).sort();
      const weekLabels = Array.from(new Set(dateGames.map((game) => game.week_label).filter(Boolean)));
      const title = weekLabels.length === 1 ? `Hosting View — ${weekLabels[0]}` : 'Hosting View';
      const totalFields = locations.reduce((sum, location) => sum + location.fields.length, 0);

      return <section key={date} className='hosting-date-section space-y-3'>
        <div><h2 className='text-xl font-bold'>{title}</h2><p className='text-base font-medium text-slate-600'>{formatDisplayDate(date)}</p></div>
        <div className='hosting-grid-scroll overflow-x-auto rounded border bg-white'>
          <table className='hosting-grid w-full border-separate border-spacing-0 text-sm leading-snug' style={{ minWidth: `${Math.max(900, 130 + totalFields * 205)}px` }}>
            <thead>
              <tr>
                <th rowSpan={2} scope='col' className='sticky left-0 top-0 z-30 w-[130px] min-w-[130px] border-b border-r bg-slate-200 px-3 py-3 text-left'>Time</th>
                {locations.map((location, locationIndex) => <th key={location.name} scope='colgroup' colSpan={location.fields.length} className={`location-group-header ${locationAccent(locationIndex)} sticky top-0 z-20 px-3 py-2.5 text-center`}>
                  <span className='block text-base font-extrabold tracking-wide text-slate-900'>{location.name}</span>
                  <span className='mt-0.5 block text-xs font-semibold text-slate-700'>{location.fields.length} {location.fields.length === 1 ? 'Field' : 'Fields'}</span>
                </th>)}
              </tr>
              <tr>
                {locations.flatMap((location, locationIndex) => location.fields.map((field, fieldIndex) => <th key={`${location.name}-${field.key}`} scope='col' className={`${locationAccent(locationIndex)} ${locationEdge(fieldIndex, location.fields.length)} sticky top-[58px] z-20 min-w-[205px] border-b px-3 py-2 text-center font-semibold ${fieldTone(field.type)}`}>
                  <span className='block'>{field.name}</span><span className='mt-0.5 block text-xs font-medium uppercase tracking-wide text-slate-600'>{fieldTypeLabel(field.type)}</span>
                </th>))}
              </tr>
            </thead>
            <tbody>
              {times.map((time) => <tr key={time}>
                <th scope='row' className='sticky left-0 z-10 whitespace-nowrap border-b border-r bg-slate-100 px-3 py-4 text-left align-top font-bold'>{formatDisplayTime(time)}</th>
                {locations.flatMap((location, locationIndex) => location.fields.map((field, fieldIndex) => {
                  const game = dateGames.find((item) => item.host_location_name === location.name && item.kickoff_time === time && gameField(item).key === field.key);
                  return <td key={`${location.name}-${field.key}`} className={`${locationAccent(locationIndex)} ${locationEdge(fieldIndex, location.fields.length)} location-schedule-cell break-words border-b p-3 align-top ${game ? fieldTone(field.type) : 'bg-white text-slate-400'}`}>
                    {game ? <div className='hosting-game min-h-[105px]'>
                      <div className='mb-2 font-bold text-slate-700'>{game.division_name}</div>
                      <div className='flex items-center gap-2 font-medium'><CommunityLogo src={game.home_team_logo_url} name={game.home_team_community_name || game.home_team_name} altText={game.home_team_logo_alt_text} size={24} /><span>{game.home_team_name}</span></div>
                      <div className='my-1 pl-8 text-xs font-semibold uppercase text-slate-500'>vs</div>
                      <div className='flex items-center gap-2 font-medium'><CommunityLogo src={game.away_team_logo_url} name={game.away_team_community_name || game.away_team_name} altText={game.away_team_logo_alt_text} size={24} /><span>{game.away_team_name}</span></div>
                    </div> : <span aria-label='No game'>—</span>}
                  </td>;
                }))}
              </tr>)}
            </tbody>
          </table>
        </div>
        <p className='text-sm text-slate-600'><strong>{dateGames.length}</strong> games across <strong>{totalFields}</strong> fields at <strong>{locations.length}</strong> host {locations.length === 1 ? 'location' : 'locations'}.</p>
      </section>;
    })}
  </div>;
}

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
  const [view, setView] = useState<ScheduleView>(searchParams.get('view') === 'hosting' ? 'hosting' : 'list');
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

  const selectView = (nextView: ScheduleView) => {
    setView(nextView);
    const query = new URLSearchParams(window.location.search);
    if (nextView === 'hosting') query.set('view', 'hosting'); else query.delete('view');
    window.history.replaceState(null, '', `${window.location.pathname}${query.size ? `?${query.toString()}` : ''}`);
  };

  return (
    <div className='public-schedule mx-auto w-[96%] max-w-[1800px] space-y-5 px-6 py-5'>
      <div className='public-schedule-header flex flex-wrap items-start justify-between gap-3'><div><h1 className='text-[26px] font-bold leading-tight'>{APP_SCHEDULE_NAME}</h1><p className='mt-1 text-base font-medium text-slate-600'>{APP_SUBTITLE}</p></div><div className='public-navigation flex flex-wrap gap-2'><Link className='inline-flex h-11 items-center rounded border px-4 text-[15px] font-medium hover:bg-slate-50' href='/tournaments'>Tournament Bracket</Link><Link className='inline-flex h-11 items-center rounded border px-4 text-[15px] font-medium hover:bg-slate-50' href='/rulebook'>Rulebook</Link></div></div>

      <div className='schedule-filters grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5'>
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

      <div className='schedule-actions flex flex-wrap gap-2'>
        <button className='h-11 rounded bg-slate-800 px-4 text-[15px] font-medium text-white' onClick={() => load(filters)}>Apply Filters</button>
        <button className='h-11 rounded border px-4 text-[15px] font-medium' onClick={() => { setFilters({}); load({}); }}>Reset</button>
        <button className='h-11 rounded border px-4 text-[15px] font-medium' onClick={() => window.print()}>Print / PDF</button>
      </div>

      <div className='schedule-view-toggle inline-flex rounded-lg border bg-white p-1' role='group' aria-label='Schedule view'>
        {([['list', 'List View'], ['hosting', 'Hosting View']] as const).map(([value, label]) => <button key={value} type='button' aria-pressed={view === value} onClick={() => selectView(value)} className={`rounded-md px-4 py-2 text-[15px] font-semibold transition ${view === value ? 'bg-slate-800 text-white shadow-sm' : 'text-slate-700 hover:bg-slate-100'}`}>{label}</button>)}
      </div>

      {loading && <div className='rounded border p-4'>Loading saved schedule...</div>}
      {empty && <div className='rounded border p-4'>{message || (hasActiveFilters ? 'No games match the selected filters.' : 'No saved schedule is currently available.')}</div>}
      {!loading && games.length > 0 && view === 'hosting' && <HostingSchedule games={games} />}
      {!loading && games.length > 0 && view === 'list' && (
        <div className='schedule-table-wrapper overflow-x-auto rounded border'>
          <table data-view='list' className='schedule-table w-full min-w-[1180px] table-fixed text-[15px] leading-snug'>
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
                  <td className='team-cell px-3 py-3'><span className='team-content flex items-center gap-2'><CommunityLogo src={g.home_team_logo_url} name={g.home_team_community_name || g.home_team_name} altText={g.home_team_logo_alt_text} size={24} />{g.home_team_name}</span></td>
                  <td className='team-cell px-3 py-3'><span className='team-content flex items-center gap-2'><CommunityLogo src={g.away_team_logo_url} name={g.away_team_community_name || g.away_team_name} altText={g.away_team_logo_alt_text} size={24} />{g.away_team_name}</span></td>
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
    <Suspense fallback={<div className='mx-auto w-[96%] max-w-[1800px] px-6 py-5 text-base'>Loading saved schedule...</div>}>
      <PublicScheduleContent />
    </Suspense>
  );
}
