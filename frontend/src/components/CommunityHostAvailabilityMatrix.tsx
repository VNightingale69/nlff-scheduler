'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { canManageCommunityHosting } from '@/lib/auth';
import { useAuthSession } from './AuthGate';

type MatrixDate = { game_date: string; week_id: string | null; week_number: number | null; label: string; is_postseason: boolean; status: string | null; date_type?: string | null; host_assignment_pending?: boolean };
type MatrixCell = { status: string; has_saved_availability: boolean; available_slot_count: number; capacity_by_size: Record<string, number> };
type MatrixRow = { community_id: string; community_name: string; host_location_id: string; host_location_name: string; cells: Record<string, MatrixCell> };
type Matrix = { season: { id: string; name: string }; dates: MatrixDate[]; rows: MatrixRow[] };
type Editor = { row: MatrixRow; date: MatrixDate } | null;

const EMPTY: Matrix = { season: { id: '', name: '' }, dates: [], rows: [] };
const month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dateLabel = (value: string) => { const [, m, d] = value.split('-').map(Number); return m && d ? `${month[m - 1]} ${d}` : value; };
const timeValue = (value?: string) => (value || '').slice(0, 5);

export default function CommunityHostAvailabilityMatrix() {
  const { currentUser: user, accessToken: token } = useAuthSession();
  const [seasons, setSeasons] = useState<any[]>([]);
  const [seasonId, setSeasonId] = useState('');
  const [matrix, setMatrix] = useState<Matrix>(EMPTY);
  const [communityFilter, setCommunityFilter] = useState('');
  const [editor, setEditor] = useState<Editor>(null);
  const [saved, setSaved] = useState<any[]>([]);
  const [areas, setAreas] = useState<any[]>([]);
  const [configs, setConfigs] = useState<any[]>([]);
  const [areaId, setAreaId] = useState('');
  const [configId, setConfigId] = useState('');
  const [startTime, setStartTime] = useState('09:00');
  const [endTime, setEndTime] = useState('17:00');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    apiFetch('/seasons?page_size=100', {}, token).then((result: any) => {
      const items = result.items || [];
      setSeasons(items);
      setSeasonId(items.find((item: any) => item.is_active)?.id || items[0]?.id || '');
    }).catch((e: Error) => setError(e.message));
  }, [token]);

  const load = async () => {
    if (!seasonId) return;
    setLoading(true);
    try { setMatrix(await apiFetch(`/host-availability-matrix?season_id=${seasonId}`, {}, token) as Matrix); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to load hosting availability.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [seasonId]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => matrix.rows.filter((row) => !communityFilter || row.community_id === communityFilter), [communityFilter, matrix.rows]);
  const groups = useMemo(() => rows.reduce<Array<{ id: string; name: string; rows: MatrixRow[] }>>((all, row) => {
    const group = all.find((item) => item.id === row.community_id);
    if (group) group.rows.push(row); else all.push({ id: row.community_id, name: row.community_name, rows: [row] });
    return all;
  }, []), [rows]);
  const communities = useMemo(() => Array.from(new Map(matrix.rows.map((row) => [row.community_id, row.community_name]))), [matrix.rows]);
  const editable = editor ? canManageCommunityHosting(user, editor.row.community_id) && editor.date.date_type !== 'BLACKOUT' && editor.date.status !== 'cancelled' : false;

  const openCell = async (row: MatrixRow, date: MatrixDate) => {
    setEditor({ row, date }); setSaved([]); setAreas([]); setConfigs([]); setError('');
    try {
      const details: any = await apiFetch(`/hosting-availabilities/saved?season_id=${seasonId}&organization_id=${row.community_id}&host_location_id=${row.host_location_id}&available_date=${date.game_date}`, {}, token);
      const items = details.items || []; setSaved(items);
      const firstRange = items[0]?.time_ranges?.[0];
      if (firstRange) { setStartTime(timeValue(firstRange.start_time)); setEndTime(timeValue(firstRange.end_time)); }
      if (canManageCommunityHosting(user, row.community_id) && date.date_type !== 'BLACKOUT') {
        const areaResult: any = await apiFetch(`/physical-field-areas?host_location_id=${row.host_location_id}&page_size=100`, {}, token);
        const areaItems = (areaResult.items || []).filter((item: any) => item.is_active); setAreas(areaItems); setAreaId(areaItems[0]?.id || '');
        if (areaItems.length) {
          const configResult: any = await apiFetch(`/field-configuration-options?physical_field_area_id=${areaItems[0].id}&page_size=100`, {}, token);
          const configItems = (configResult.items || []).filter((item: any) => item.is_active); setConfigs(configItems); setConfigId(configItems[0]?.id || '');
        }
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to load availability details.'); }
  };

  const changeArea = async (id: string) => {
    setAreaId(id); const result: any = await apiFetch(`/field-configuration-options?physical_field_area_id=${id}&page_size=100`, {}, token);
    const items = (result.items || []).filter((item: any) => item.is_active); setConfigs(items); setConfigId(items[0]?.id || '');
  };

  const save = async () => {
    if (!editor || !editable || !areaId || !configId) return;
    setSaving(true);
    try {
      await apiFetch('/hosting-availabilities/bulk-upsert', { method: 'POST', body: JSON.stringify({ slots: [{ season_id: seasonId, week_id: editor.date.week_id, organization_id: editor.row.community_id, host_location_id: editor.row.host_location_id, physical_field_area_id: areaId, field_configuration_option_id: configId, available_date: editor.date.game_date, start_time: `${startTime}:00`, end_time: `${endTime}:00`, is_available: true }] }) }, token);
      setEditor(null); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save availability.'); }
    finally { setSaving(false); }
  };

  const cellPresentation = (date: MatrixDate, cell?: MatrixCell) => {
    if (date.date_type === 'BLACKOUT') return { label: 'BLK', css: 'bg-amber-100 text-amber-900' };
    if (String(date.status).toLowerCase() === 'cancelled') return { label: 'CAN', css: 'bg-rose-50 text-rose-700' };
    if (date.host_assignment_pending || cell?.status === 'DEFERRED') return { label: 'TBD', css: 'bg-amber-50 text-amber-800' };
    if (cell?.has_saved_availability) return { label: '✓', css: 'bg-emerald-50 text-emerald-800' };
    return { label: '—', css: 'bg-slate-100 text-slate-400' };
  };

  return <div className='space-y-4'>
    <header className='rounded border bg-white p-4 shadow-sm'>
      <div className='flex flex-wrap items-end justify-between gap-4'><div><p className='text-sm font-semibold uppercase tracking-wide text-slate-500'>Community Management</p><h1 className='text-2xl font-bold text-slate-900'>Hosting Availability</h1></div>
        <div className='flex flex-wrap gap-3'><label className='text-sm font-medium'>Season<select aria-label='Season' className='mt-1 block rounded border p-2 font-normal' value={seasonId} onChange={(e) => setSeasonId(e.target.value)}>{seasons.map((season) => <option key={season.id} value={season.id}>{season.name}</option>)}</select></label>
        <label className='text-sm font-medium'>Community<select aria-label='Community filter' className='mt-1 block rounded border p-2 font-normal' value={communityFilter} onChange={(e) => setCommunityFilter(e.target.value)}><option value=''>All Communities</option>{communities.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label></div>
      </div>
      <div className='mt-4 flex flex-wrap gap-4 text-xs text-slate-600'><span><b className='text-emerald-700'>✓</b> Available</span><span><b>TBD</b> Hosting TBD</span><span><b>—</b> Not available</span><span><b className='text-amber-800'>BLK</b> League blackout</span><span><b className='text-rose-700'>CAN</b> Cancelled</span></div>
      {error ? <p className='mt-3 rounded bg-rose-50 p-2 text-sm text-rose-700'>{error}</p> : null}
    </header>
    <div className='max-h-[70vh] overflow-auto rounded border bg-white shadow-sm'><table className='min-w-max border-collapse text-sm'><thead className='sticky top-0 z-30 bg-slate-100'><tr><th className='sticky left-0 z-40 w-44 border bg-slate-100 px-3 py-2 text-left'>Community</th><th className='sticky left-44 z-40 w-56 border bg-slate-100 px-3 py-2 text-left'>Host Location</th>{matrix.dates.map((date) => <th key={date.game_date} className={`min-w-20 border px-2 py-2 text-center ${date.date_type === 'BLACKOUT' ? 'bg-amber-100' : date.is_postseason ? 'bg-indigo-50' : ''}`}><span>{date.is_postseason ? 'P ' : ''}{dateLabel(date.game_date)}</span><span className='block max-w-24 truncate text-[10px] font-normal'>{date.date_type === 'BLACKOUT' ? date.label || 'Blackout' : date.is_postseason ? date.label || 'Playoff' : `Week ${date.week_number ?? '—'}`}</span></th>)}</tr></thead>
      <tbody>{loading ? <tr><td colSpan={matrix.dates.length + 2} className='p-5 text-slate-500'>Loading matrix…</td></tr> : groups.flatMap((group) => group.rows.map((row, index) => { const own = canManageCommunityHosting(user, row.community_id); return <tr key={row.host_location_id} className={`border-t ${own ? 'bg-indigo-50/30' : ''}`}><td className={`sticky left-0 border-r px-3 py-2 align-top font-bold ${own ? 'bg-indigo-50' : 'bg-white'}`}>{index === 0 ? <>{group.name}{own ? <span className='ml-2 inline-block rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-indigo-700'>My Community</span> : null}</> : null}</td><td className={`sticky left-44 border-r px-3 py-2 font-medium ${own ? 'bg-indigo-50' : 'bg-white'}`}>{row.host_location_name}</td>{matrix.dates.map((date) => { const presentation = cellPresentation(date, row.cells[date.game_date]); const canClick = date.date_type !== 'BLACKOUT'; return <td key={date.game_date} className='border p-1 text-center'><button aria-label={`${row.community_name}, ${row.host_location_name}, ${date.game_date}: ${presentation.label}`} disabled={!canClick} onClick={() => openCell(row, date)} className={`h-9 w-full rounded font-bold ${presentation.css} ${own && canClick ? 'cursor-pointer ring-1 ring-inset ring-indigo-200 hover:ring-indigo-500' : 'cursor-default'}`}>{presentation.label}</button></td>; })}</tr>; }))}</tbody></table></div>
    {editor ? <div role='dialog' aria-modal='true' aria-label='Hosting availability details' className='fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4'><div className='w-full max-w-lg rounded-lg bg-white p-5 shadow-xl'><div className='flex justify-between gap-3'><div><h2 className='text-xl font-bold'>{editor.row.host_location_name}</h2><p className='text-sm text-slate-600'>{editor.row.community_name} · Week {editor.date.week_number ?? '—'} · {editor.date.game_date}</p></div>{!editable ? <span className='h-fit rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600'>VIEW ONLY</span> : null}</div>
      {saved.length ? <div className='mt-4 rounded bg-emerald-50 p-3 text-sm text-emerald-900'><b>Available</b>{saved[0]?.time_ranges?.length ? ` · ${timeValue(saved[0].time_ranges[0].start_time)}–${timeValue(saved[0].time_ranges[0].end_time)}` : ''}<div className='mt-1 text-xs'>{saved.length} field configuration{saved.length === 1 ? '' : 's'} saved</div></div> : <p className='mt-4 rounded bg-slate-50 p-3 text-sm text-slate-600'>No hosting availability configured.</p>}
      {editable ? <div className='mt-4 grid gap-3'><label className='text-sm font-medium'>Field area<select className='mt-1 w-full rounded border p-2 font-normal' value={areaId} onChange={(e) => changeArea(e.target.value)}>{areas.map((area) => <option key={area.id} value={area.id}>{area.name}</option>)}</select></label><label className='text-sm font-medium'>Field configuration<select className='mt-1 w-full rounded border p-2 font-normal' value={configId} onChange={(e) => setConfigId(e.target.value)}>{configs.map((config) => <option key={config.id} value={config.id}>{config.name}</option>)}</select></label><div className='grid grid-cols-2 gap-3'><label className='text-sm font-medium'>Available from<input type='time' className='mt-1 w-full rounded border p-2 font-normal' value={startTime} onChange={(e) => setStartTime(e.target.value)} /></label><label className='text-sm font-medium'>Available until<input type='time' className='mt-1 w-full rounded border p-2 font-normal' value={endTime} onChange={(e) => setEndTime(e.target.value)} /></label></div></div> : null}
      <div className='mt-5 flex justify-end gap-2'><button className='rounded border px-4 py-2 text-sm font-semibold' onClick={() => setEditor(null)}>{editable ? 'Cancel' : 'Close'}</button>{editable ? <button disabled={saving || !areaId || !configId || startTime >= endTime} className='rounded bg-indigo-700 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-300' onClick={save}>{saving ? 'Saving…' : 'Save'}</button> : null}</div></div></div> : null}
  </div>;
}
