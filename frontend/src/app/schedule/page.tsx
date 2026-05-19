'use client';
import { useEffect, useMemo, useState } from 'react';
import { API_URL } from '@/lib/api';

type Game = { id: string; game_date: string; kickoff_time: string; host_location_name: string; field_name: string; division_name: string; home_team_name: string; away_team_name: string; game_status_label: string; };

export default function PublicSchedulePage() {
  const [games, setGames] = useState<Game[]>([]);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [options, setOptions] = useState<any>({ host_locations: [], organizations: [], divisions: [], weeks: [], teams: [], statuses: [] });
  const [loading, setLoading] = useState(true);
  const load = async (activeFilters: Record<string, string> = filters) => {
    setLoading(true);
    const q = new URLSearchParams(Object.fromEntries(Object.entries(activeFilters).filter(([, v]) => v)));
    const [gamesRes, optionsRes] = await Promise.all([
      fetch(`${API_URL}/public/games?${q.toString()}`),
      fetch(`${API_URL}/public/schedule-filters`),
    ]);
    setGames(((await gamesRes.json()).items || []));
    setOptions(await optionsRes.json());
    setLoading(false);
  };
  useEffect(() => { load({}); }, []);
  const empty = useMemo(() => !loading && games.length === 0, [loading, games.length]);

  return <div className='mx-auto max-w-6xl space-y-4 p-4'><h1 className='text-2xl font-bold'>Northern Lakes Flag Football Public Schedule</h1>
    <div className='grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3'>
      <select className='rounded border p-2' value={filters.host_location_id||''} onChange={e=>setFilters({...filters,host_location_id:e.target.value})}><option value=''>All Host Locations</option>{options.host_locations.map((o:any)=><option key={o.id} value={o.id}>{o.name}</option>)}</select>
      <select className='rounded border p-2' value={filters.organization_id||''} onChange={e=>setFilters({...filters,organization_id:e.target.value})}><option value=''>All Communities</option>{options.organizations.map((o:any)=><option key={o.id} value={o.id}>{o.name}</option>)}</select>
      <select className='rounded border p-2' value={filters.division_id||''} onChange={e=>setFilters({...filters,division_id:e.target.value})}><option value=''>All Divisions</option>{options.divisions.map((o:any)=><option key={o.id} value={o.id}>{o.name}</option>)}</select>
      <select className='rounded border p-2' value={filters.week_id||''} onChange={e=>setFilters({...filters,week_id:e.target.value})}><option value=''>All Weeks</option>{options.weeks.map((o:any)=><option key={o.id} value={o.id}>Week {o.week_number}</option>)}</select>
      <select className='rounded border p-2' value={filters.team_id||''} onChange={e=>setFilters({...filters,team_id:e.target.value})}><option value=''>All Teams</option>{options.teams.map((o:any)=><option key={o.id} value={o.id}>{o.name}</option>)}</select>
      <select className='rounded border p-2' value={filters.status_code||''} onChange={e=>setFilters({...filters,status_code:e.target.value})}><option value=''>All Statuses</option>{options.statuses.map((o:any)=><option key={o.code} value={o.code}>{o.label}</option>)}</select>
    </div>
    <div className='flex gap-2'><button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={() => load(filters)}>Apply Filters</button><button className='rounded border px-3 py-2' onClick={()=>{ setFilters({}); load({}); }}>Reset</button></div>
    {loading && <div className='rounded border p-4'>Loading published schedule...</div>}
    {empty && <div className='rounded border p-4'>No published games found for the selected filters.</div>}
    {!loading && games.length>0 && <div className='overflow-x-auto rounded border'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr><th className='p-2'>Date</th><th className='p-2'>Time</th><th className='p-2'>Host location</th><th className='p-2'>Field</th><th className='p-2'>Division</th><th className='p-2'>Home team</th><th className='p-2'>Away team</th><th className='p-2'>Game status</th></tr></thead><tbody>{games.map(g=><tr key={g.id} className='border-t'><td className='p-2'>{g.game_date}</td><td className='p-2'>{g.kickoff_time}</td><td className='p-2'>{g.host_location_name}</td><td className='p-2'>{g.field_name}</td><td className='p-2'>{g.division_name}</td><td className='p-2'>{g.home_team_name}</td><td className='p-2'>{g.away_team_name}</td><td className='p-2'>{g.game_status_label}</td></tr>)}</tbody></table></div>}
  </div>;
}
