'use client';

import { useEffect, useMemo, useState } from 'react';
import { API_URL } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

type Game = { date: string; kickoff: string; division: string; home_team: string; away_team: string; host_organization?: string; host_location?: string; field: string; field_type?: string; publication_status: string };
type Week = { week_id: string; week_number: number; label: string; date: string; publication_status: string; games: Game[] };
type Option = { id: string; name?: string; label?: string };
type Payload = { season: { name: string } | null; weeks: Week[]; my_organization?: { name: string } | null; options?: Record<string, Option[]> };
type View = 'date' | 'host' | 'team' | 'division' | 'hosting';

const statusLabel = (status: string) => status === 'PUBLISHED_CHANGES_PENDING' ? 'Published — Changes Pending' : status === 'PUBLISHED' ? 'Published' : 'Draft';
const statusTone = (status: string) => status === 'PUBLISHED' ? 'bg-emerald-100 text-emerald-800' : status === 'PUBLISHED_CHANGES_PENDING' ? 'bg-amber-100 text-amber-900' : 'bg-slate-200 text-slate-800';

export default function ScheduleReviewPage() {
  const [payload, setPayload] = useState<Payload>({ season: null, weeks: [] });
  const [scope, setScope] = useState('my_organization');
  const [view, setView] = useState<View>('date');
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async (nextScope = scope, nextFilters = filters) => {
    setLoading(true); setError('');
    const query = new URLSearchParams({ scope: nextScope });
    Object.entries(nextFilters).forEach(([key, value]) => value && query.set(key, value));
    const response = await fetch(`${API_URL}/schedule-review?${query}`, { headers: { Authorization: `Bearer ${getToken()}` } });
    const body = await response.json();
    if (!response.ok) setError(body.detail || 'Unable to load schedule review.'); else setPayload(body);
    setLoading(false);
  };
  useEffect(() => { load('my_organization', {}); }, []);
  const games = useMemo(() => payload.weeks.flatMap((week) => week.games.map((game) => ({ ...game, week }))), [payload]);
  const hasDrafts = payload.weeks.some((week) => week.publication_status !== 'PUBLISHED');
  const option = (key: string, label: string) => <select aria-label={label} className='h-10 rounded border bg-white px-3' value={filters[key] || ''} onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}><option value=''>All {label}</option>{(payload.options?.[key.replace('_id', '') + 's'] || []).map((item) => <option key={item.id} value={item.id}>{item.label || item.name}</option>)}</select>;
  const download = async () => {
    const response = await fetch(`${API_URL}/schedule-review/export.csv?scope=${scope}`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!response.ok) { setError('Unable to export schedule review.'); return; }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'schedule-review.csv'; anchor.click(); URL.revokeObjectURL(url);
  };

  return <div className='mx-auto w-full max-w-[1800px] space-y-5 print:max-w-none'>
    <header className='flex flex-wrap items-center justify-between gap-3'><div className='flex items-center gap-3'><h1 className='text-2xl font-bold'>Schedule Review</h1><span className='rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold uppercase tracking-wide'>Read Only</span></div><strong>Season: {payload.season?.name || 'Active season'}</strong></header>
    <div className='rounded border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950'><strong>This schedule includes weeks that have not yet been published.</strong><br />Draft games, times, fields, and matchups may change before official publication.</div>
    {hasDrafts && <div className='hidden text-center text-lg font-bold print:block'>PREPUBLISHED SCHEDULE — SUBJECT TO CHANGE</div>}
    <section className='space-y-3 rounded border bg-white p-4 print:hidden'>
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-7'>
        <select aria-label='Organization scope' className='h-10 rounded border px-3' value={scope} onChange={(e) => { setScope(e.target.value); load(e.target.value, filters); }}><option value='my_organization'>My Organization{payload.my_organization?.name ? ` — ${payload.my_organization.name}` : ''}</option><option value='league'>Entire League</option></select>
        {option('week_id', 'Weeks')}{option('division_id', 'Divisions')}{option('host_location_id', 'Host Locations')}{option('team_id', 'Teams')}{option('field_id', 'Fields')}
        <input aria-label='Date' type='date' className='h-10 rounded border px-3' value={filters.date || ''} onChange={(e) => setFilters({ ...filters, date: e.target.value })} />
      </div>
      <div className='flex flex-wrap gap-2'><button className='rounded bg-slate-800 px-4 py-2 text-white' onClick={() => load()}>Apply Filters</button><button className='rounded border px-4 py-2' onClick={() => { setFilters({}); load(scope, {}); }}>Reset</button><button className='rounded border px-4 py-2' onClick={download}>Export CSV</button><button className='rounded border px-4 py-2' onClick={() => window.print()}>Print</button></div>
    </section>
    <div className='flex flex-wrap gap-2 print:hidden'>{([['date', 'By Date'], ['host', 'By Host Location'], ['team', 'By Team'], ['division', 'By Division'], ['hosting', 'Hosting View']] as const).map(([key, label]) => <button key={key} aria-pressed={view === key} className={`rounded px-3 py-2 ${view === key ? 'bg-slate-800 text-white' : 'border bg-white'}`} onClick={() => setView(key)}>{label}</button>)}</div>
    {loading && <p className='rounded border bg-white p-4'>Loading saved schedule…</p>}{error && <p className='rounded border border-red-200 bg-red-50 p-4 text-red-800'>{error}</p>}
    {!loading && !error && payload.weeks.map((week) => <section key={week.week_id} className='space-y-3 rounded border bg-white p-4 break-inside-avoid'>
      <div className='flex flex-wrap items-center gap-3'><h2 className='text-lg font-bold'>{week.label} — {formatDisplayDate(week.date)}</h2><span className={`rounded-full px-3 py-1 text-xs font-bold ${statusTone(week.publication_status)}`}>{statusLabel(week.publication_status)}</span></div>
      {week.publication_status === 'PUBLISHED_CHANGES_PENDING' && <p className='text-sm text-amber-800'>Official public version differs from the current administrative schedule.</p>}
      {!week.games.length ? <p className='text-sm text-slate-500'>No games match the selected filters.</p> : view === 'hosting' ? <HostingGrid games={week.games} /> : <GameTable games={[...week.games].sort((a, b) => groupValue(a, view).localeCompare(groupValue(b, view)) || a.kickoff.localeCompare(b.kickoff))} groupBy={view} />}
    </section>)}
  </div>;
}

function groupValue(game: Game, view: Exclude<View, 'hosting'>) { return view === 'host' ? game.host_location || '' : view === 'team' ? game.home_team : view === 'division' ? game.division : game.date; }
function GameTable({ games, groupBy }: { games: Game[]; groupBy: Exclude<View, 'hosting'> }) { return <div className='overflow-x-auto'><table className='w-full min-w-[900px] text-sm'><thead className='bg-slate-100'><tr>{['Date', 'Time', 'Division', 'Home Team', 'Away Team', 'Host Location', 'Field'].map((h) => <th key={h} className='p-2 text-left'>{h}</th>)}</tr></thead><tbody>{games.map((g, index) => <tr key={`${g.date}-${g.kickoff}-${g.home_team}-${index}`} className='border-t'><td className='p-2'>{formatDisplayDate(g.date)}</td><td className='p-2'>{formatDisplayTime(g.kickoff)}</td><td className='p-2'>{g.division}</td><td className='p-2'>{g.home_team}</td><td className='p-2'>{g.away_team}</td><td className='p-2'>{g.host_location || 'Not assigned'}</td><td className='p-2'>{g.field}</td></tr>)}</tbody></table></div>; }
function HostingGrid({ games }: { games: Game[] }) { const fields = Array.from(new Set(games.map((g) => `${g.host_location || 'Not assigned'} · ${g.field}`))); const times = Array.from(new Set(games.map((g) => g.kickoff))).sort(); return <div className='overflow-x-auto'><table className='w-full min-w-[850px] text-sm'><thead><tr><th className='bg-slate-100 p-2 text-left'>Time</th>{fields.map((field) => <th key={field} className='bg-slate-100 p-2'>{field}</th>)}</tr></thead><tbody>{times.map((time) => <tr key={time} className='border-t'><th className='p-2 text-left'>{formatDisplayTime(time)}</th>{fields.map((field) => { const game = games.find((g) => g.kickoff === time && `${g.host_location || 'Not assigned'} · ${g.field}` === field); return <td key={field} className='border-l p-2 text-center'>{game ? <><strong>{game.division}</strong><br />{game.home_team}<br /><span className='text-slate-500'>vs</span><br />{game.away_team}</> : '—'}</td>; })}</tr>)}</tbody></table></div>; }
