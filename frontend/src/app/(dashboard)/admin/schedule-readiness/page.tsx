'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

type ReadinessRow = {
  division_id: string;
  division_label: string;
  field_type_required: 'SMALL' | 'LARGE';
  number_of_teams: number;
  estimated_games_needed: number;
  available_matching_slots: number;
  status: 'READY' | 'SHORT' | 'NO TEAMS';
};

type ReadinessTotals = {
  total_teams: number;
  total_games_needed: number;
  total_small_field_slots: number;
  total_large_field_slots: number;
  total_open_slots: number;
};

export default function ScheduleReadinessPage() {
  const token = getToken();
  const [rows, setRows] = useState<ReadinessRow[]>([]);
  const [totals, setTotals] = useState<ReadinessTotals | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const data: any = await apiFetch('/schedule-readiness', {}, token);
        setRows(data?.rows || []);
        setTotals(data?.totals || null);
      } catch (e: any) {
        setError(e?.message || 'Failed to load schedule readiness report');
      }
    })();
  }, []);

  const statusClass = (status: ReadinessRow['status']) => {
    if (status === 'READY') return 'bg-green-100 text-green-700';
    if (status === 'SHORT') return 'bg-red-100 text-red-700';
    return 'bg-slate-100 text-slate-700';
  };

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Schedule Readiness</h1>
      <p className='text-sm text-slate-600'>Capacity validation report only. This page does not create matchups or auto-schedule games.</p>
      {error ? <div className='rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700'>{error}</div> : null}
      {totals ? (
        <div className='grid gap-3 rounded border bg-white p-3 text-sm md:grid-cols-5'>
          <div><div className='text-slate-500'>Total teams</div><div className='font-semibold'>{totals.total_teams}</div></div>
          <div><div className='text-slate-500'>Total games needed</div><div className='font-semibold'>{totals.total_games_needed}</div></div>
          <div><div className='text-slate-500'>Total small-field slots</div><div className='font-semibold'>{totals.total_small_field_slots}</div></div>
          <div><div className='text-slate-500'>Total large-field slots</div><div className='font-semibold'>{totals.total_large_field_slots}</div></div>
          <div><div className='text-slate-500'>Total open slots</div><div className='font-semibold'>{totals.total_open_slots}</div></div>
        </div>
      ) : null}
      <div className='overflow-auto rounded border bg-white'>
        <table className='min-w-full text-sm'>
          <thead><tr className='border-b text-left'><th className='p-2'>Division</th><th className='p-2'>Field Type Required</th><th className='p-2'>Number of Teams</th><th className='p-2'>Estimated Games Needed</th><th className='p-2'>Available Matching Slots</th><th className='p-2'>Status</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.division_id} className='border-b'>
                <td className='p-2'>{row.division_label}</td><td className='p-2'>{row.field_type_required}</td><td className='p-2'>{row.number_of_teams}</td><td className='p-2'>{row.estimated_games_needed}</td><td className='p-2'>{row.available_matching_slots}</td>
                <td className='p-2'><span className={`rounded px-2 py-1 text-xs font-semibold ${statusClass(row.status)}`}>{row.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
