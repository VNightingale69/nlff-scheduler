'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';

const WEEK_STATUSES = ['draft', 'active', 'locked', 'completed', 'cancelled'];
const WEEK_DATE_TYPES = ['REGULAR_SEASON', 'BLACKOUT', 'PLAYOFF'];

const emptyForm = {
  season_id: '',
  week_number: '',
  label: '',
  start_date: '',
  end_date: '',
  primary_game_date: '',
  date_type: 'REGULAR_SEASON',
  notes: '',
  status: 'draft',
};

const statusClass: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700 border-slate-200',
  active: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  locked: 'bg-blue-100 text-blue-800 border-blue-200',
  completed: 'bg-slate-800 text-white border-slate-800',
  cancelled: 'bg-red-100 text-red-800 border-red-200',
};

const dateTypeClass: Record<string, string> = {
  REGULAR_SEASON: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  BLACKOUT: 'bg-slate-800 text-white border-slate-800',
  PLAYOFF: 'bg-amber-100 text-amber-900 border-amber-300',
};

const titleCase = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

const formatDate = (value: string | null | undefined) => {
  if (!value) return '—';
  const datePart = String(value).split('T')[0];
  const [year, month, day] = datePart.split('-').map(Number);
  if (!year || !month || !day) return String(value);
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, day)));
};

const weekOptionLabel = (week: any) => week.label || `Week ${week.week_number}`;

export default function WeeksPage() {
  const { accessToken: token } = useAuthSession();
  const [items, setItems] = useState<any[]>([]);
  const [seasons, setSeasons] = useState<any[]>([]);
  const [form, setForm] = useState<any>(emptyForm);
  const [id, setId] = useState('');
  const [filters, setFilters] = useState({ season_id: '', status: '', start_date: '', end_date: '', search: '' });
  const [error, setError] = useState('');

  const filterQuery = useMemo(() => {
    const params = new URLSearchParams({ page_size: '300' });
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params.set(key === 'search' ? 'search' : key, value);
    });
    return params.toString();
  }, [filters]);

  const load = async () => {
    const [weekResponse, seasonResponse]: any = await Promise.all([
      apiFetch(`/weeks?${filterQuery}`, {}, token),
      apiFetch('/seasons?page_size=200', {}, token),
    ]);
    setItems(weekResponse.items || []);
    setSeasons(seasonResponse.items || []);
  };

  useEffect(() => {
    load().catch((e) => setError(e?.message || 'Unable to load weeks'));
  }, [filterQuery]);

  const seasonName = (seasonId: string) => seasons.find((season: any) => season.id === seasonId)?.name || '—';

  const validate = () => {
    if (!form.season_id) return 'Season is required.';
    if (!form.week_number) return 'Week number is required.';
    if (!form.start_date) return 'Start date is required.';
    if (!form.end_date) return 'End date is required.';
    if (!form.primary_game_date) return 'Primary game date is required.';
    if (form.end_date < form.start_date) return 'End date cannot be before start date.';
    if (form.primary_game_date < form.start_date || form.primary_game_date > form.end_date) return 'Primary game date must fall within the start/end date range.';
    const duplicate = items.find((week) => week.id !== id && week.season_id === form.season_id && Number(week.week_number) === Number(form.week_number));
    if (duplicate) return 'Week numbers must be unique within a season.';
    return '';
  };

  const save = async () => {
    setError('');
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    try {
      const payload = { ...form, week_number: Number(form.week_number) };
      if (id) await apiFetch(`/weeks/${id}`, { method: 'PUT', body: JSON.stringify(payload) }, token);
      else await apiFetch('/weeks', { method: 'POST', body: JSON.stringify(payload) }, token);
      setForm(emptyForm);
      setId('');
      await load();
    } catch (e: any) {
      setError(e?.message || 'Unable to save week');
    }
  };

  const edit = (week: any) => {
    setId(week.id);
    setForm({
      season_id: week.season_id || '',
      week_number: week.week_number ? String(week.week_number) : '',
      label: week.label || '',
      start_date: week.start_date || '',
      end_date: week.end_date || '',
      primary_game_date: week.primary_game_date || week.start_date || '',
      date_type: week.date_type || 'REGULAR_SEASON',
      notes: week.notes || '',
      status: week.status || 'draft',
    });
  };

  const duplicate = (week: any) => {
    setId('');
    setForm({
      season_id: week.season_id || '',
      week_number: '',
      label: week.label ? `${week.label} Copy` : '',
      start_date: week.start_date || '',
      end_date: week.end_date || '',
      primary_game_date: week.primary_game_date || week.start_date || '',
      date_type: week.date_type || 'REGULAR_SEASON',
      notes: week.notes || '',
      status: 'draft',
    });
  };

  const lockWeek = async (week: any) => {
    setError('');
    try {
      await apiFetch(`/weeks/${week.id}`, { method: 'PUT', body: JSON.stringify({ ...week, status: 'locked' }) }, token);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Unable to lock week');
    }
  };

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Season Weeks / Game Dates</h1>
      {error ? <div className='rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700'>{error}</div> : null}

      <section className='rounded border bg-white p-4'>
        <h2 className='mb-3 font-semibold'>{id ? 'Edit Week' : 'Create Week'}</h2>
        <div className='grid gap-3 md:grid-cols-4'>
          <label className='text-sm'>Season<select className='mt-1 w-full rounded border p-2' value={form.season_id} onChange={(e) => setForm({ ...form, season_id: e.target.value })}><option value=''>Season</option>{seasons.map((season: any) => <option key={season.id} value={season.id}>{season.name}</option>)}</select></label>
          <label className='text-sm'>Week Number<input className='mt-1 w-full rounded border p-2' type='number' min='1' value={form.week_number} onChange={(e) => setForm({ ...form, week_number: e.target.value })} /></label>
          <label className='text-sm'>Week Name / Label<input className='mt-1 w-full rounded border p-2' placeholder='Opening Week' value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></label>
          <label className='text-sm'>Status<select className='mt-1 w-full rounded border p-2' value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>{WEEK_STATUSES.map((status) => <option key={status} value={status}>{titleCase(status)}</option>)}</select></label>
          <label className='text-sm'>Date Type<select className='mt-1 w-full rounded border p-2' value={form.date_type} onChange={(e) => setForm({ ...form, date_type: e.target.value })}>{WEEK_DATE_TYPES.map((dateType) => <option key={dateType} value={dateType}>{dateType.replace('_', ' ')}</option>)}</select></label>
          <label className='text-sm'>Start Date<input className='mt-1 w-full rounded border p-2' type='date' value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></label>
          <label className='text-sm'>End Date<input className='mt-1 w-full rounded border p-2' type='date' value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></label>
          <label className='text-sm'>Primary Game Date<input className='mt-1 w-full rounded border p-2' type='date' value={form.primary_game_date} onChange={(e) => setForm({ ...form, primary_game_date: e.target.value })} /></label>
          <label className='text-sm md:col-span-4'>Notes<textarea className='mt-1 w-full rounded border p-2' rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
        </div>
        <div className='mt-3 flex gap-2'>
          <button className='rounded bg-emerald-700 px-4 py-2 text-white' onClick={save}>{id ? 'Update Week' : 'Create Week'}</button>
          {id ? <button className='rounded border px-4 py-2' onClick={() => { setId(''); setForm(emptyForm); }}>Cancel</button> : null}
        </div>
      </section>

      <section className='rounded border bg-white p-4'>
        <h2 className='mb-3 font-semibold'>Quick Filters</h2>
        <div className='grid gap-2 md:grid-cols-5'>
          <select className='rounded border p-2' value={filters.season_id} onChange={(e) => setFilters({ ...filters, season_id: e.target.value })}><option value=''>All Seasons</option>{seasons.map((season: any) => <option key={season.id} value={season.id}>{season.name}</option>)}</select>
          <select className='rounded border p-2' value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value=''>All Statuses</option>{WEEK_STATUSES.map((status) => <option key={status} value={status}>{titleCase(status)}</option>)}</select>
          <input className='rounded border p-2' type='date' value={filters.start_date} onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} aria-label='Date range start' />
          <input className='rounded border p-2' type='date' value={filters.end_date} onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} aria-label='Date range end' />
          <input className='rounded border p-2' placeholder='Search by week label' value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
        </div>
      </section>

      <div className='overflow-auto rounded border bg-white'>
        <table className='min-w-full text-sm'>
          <thead><tr className='border-b bg-slate-50 text-left'><th className='p-2'>Season</th><th className='p-2'>Week #</th><th className='p-2'>Week Label</th><th className='p-2'>Start Date</th><th className='p-2'>End Date</th><th className='p-2'>Primary Game Date</th><th className='p-2'>Date Type</th><th className='p-2'>Status</th><th className='p-2'>Hosting Availability Count</th><th className='p-2'>Generated Slots Count</th><th className='p-2'>Scheduled Games Count</th><th className='p-2'>Actions</th></tr></thead>
          <tbody>{items.map((week: any) => <tr key={week.id} className='border-b align-top'><td className='p-2'>{seasonName(week.season_id)}</td><td className='p-2'>Week {week.week_number}</td><td className='p-2'>{weekOptionLabel(week)}</td><td className='p-2'>{formatDate(week.start_date)}</td><td className='p-2'>{formatDate(week.end_date)}</td><td className='p-2'>{formatDate(week.primary_game_date)}</td><td className='p-2'><span className={`rounded-full border px-2 py-1 text-xs font-semibold ${dateTypeClass[week.date_type] || dateTypeClass.REGULAR_SEASON}`}>{(week.date_type || 'REGULAR_SEASON').replace('_', ' ')}</span></td><td className='p-2'><span className={`rounded-full border px-2 py-1 text-xs font-semibold ${statusClass[week.status] || statusClass.draft}`}>{titleCase(week.status || 'draft')}</span></td><td className='p-2'>{week.hosting_availability_count ?? 0} host sites</td><td className='p-2'>{week.generated_slots_count ?? 0} slots</td><td className='p-2'>{week.scheduled_games_count ?? 0} games</td><td className='p-2'><div className='flex min-w-48 flex-col gap-1'><button className='text-left text-blue-700 underline' onClick={() => edit(week)}>Edit Week</button><Link className='text-blue-700 underline' href={`/admin/hosting-availability?week_id=${week.id}&start_date=${week.start_date}&end_date=${week.end_date}`}>View Hosting Availability</Link><Link className='text-blue-700 underline' href={`/admin/host-availability-matrix?season_id=${week.season_id}&game_date=${week.primary_game_date || week.start_date}`}>View Host Availability Matrix</Link><Link className='text-blue-700 underline' href={`/admin/generated-slots?week_id=${week.id}&start_date=${week.start_date}&end_date=${week.end_date}`}>View Generated Slots</Link><Link className='text-blue-700 underline' href={`/admin/schedule-readiness?week_id=${week.id}&start_date=${week.start_date}&end_date=${week.end_date}`}>View Schedule Readiness</Link><button className='text-left text-blue-700 underline' onClick={() => lockWeek(week)}>Lock Week</button><button className='text-left text-blue-700 underline' onClick={() => duplicate(week)}>Duplicate Week Setup</button><Link className='text-blue-700 underline' href={`/admin/manual-schedule-builder?season_id=${week.season_id}&week_id=${week.id}`}>Manual Schedule Builder</Link><Link className='text-blue-700 underline' href={`/admin/schedule-management?week_id=${week.id}`}>Schedule Management</Link><Link className='text-blue-700 underline' href={`/schedule?week_id=${week.id}`}>Published Schedule</Link></div></td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
