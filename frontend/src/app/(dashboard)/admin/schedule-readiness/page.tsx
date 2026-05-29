'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

type ReadinessRow = {
  division_id: string;
  division_label: string;
  field_type_required: 'SMALL' | 'MEDIUM' | 'LARGE';
  number_of_teams: number;
  minimum_unique_matchups: number;
  target_scheduled_games: number | null;
  available_matching_slots: number;
  status: 'READY' | 'SHORT' | 'NO TEAMS';
};

type ReadinessTotals = {
  total_teams: number;
  total_minimum_unique_matchups: number;
  total_target_scheduled_games: number | null;
  total_small_field_slots: number;
  total_medium_field_slots: number;
  total_large_field_slots: number;
  total_open_slots: number;
};

const MINIMUM_UNIQUE_MATCHUPS_HELP =
  'This represents the minimum number of unique matchups required for a single round-robin format before repeat matchups or double headers are considered.';

export default function ScheduleReadinessPage() {
  const token = getToken();
  const [rows, setRows] = useState<ReadinessRow[]>([]);
  const [totals, setTotals] = useState<ReadinessTotals | null>(null);
  const [error, setError] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const data: any = await apiFetch('/schedule-readiness', {}, token);
        setRows(data?.rows || []);
        setTotals(data?.totals || null);
        setWarnings(data?.warnings || []);
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
      {warnings.length ? <div className='rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800'><div className='font-semibold'>Validation warnings</div><ul className='list-disc pl-5'>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
      {totals ? (
        <div className='grid gap-3 rounded border bg-white p-3 text-sm md:grid-cols-7'>
          <div><div className='text-slate-500'>Total Teams</div><div className='font-semibold'>{totals.total_teams}</div></div>
          <div><div className='text-slate-500'>Total Minimum Unique Matchups</div><div className='font-semibold'>{totals.total_minimum_unique_matchups}</div></div>
          <div><div className='text-slate-500'>Total Target Scheduled Games</div><div className='font-semibold'>{totals.total_target_scheduled_games ?? '—'}</div></div>
          <div><div className='text-slate-500'>Total Small Slots</div><div className='font-semibold'>{totals.total_small_field_slots}</div></div>
          <div><div className='text-slate-500'>Total Medium Slots</div><div className='font-semibold'>{totals.total_medium_field_slots}</div></div>
          <div><div className='text-slate-500'>Total Large Slots</div><div className='font-semibold'>{totals.total_large_field_slots}</div></div>
          <div><div className='text-slate-500'>Total Open Slots</div><div className='font-semibold'>{totals.total_open_slots}</div></div>
        </div>
      ) : null}
      <div className='overflow-auto rounded border bg-white'>
        <table className='min-w-full text-sm'>
          <thead>
            <tr className='border-b text-left'>
              <th className='p-2'>Division</th>
              <th className='p-2'>Field Type Required</th>
              <th className='p-2'>Number of Teams</th>
              <th className='p-2'>
                <span title={MINIMUM_UNIQUE_MATCHUPS_HELP} className='cursor-help underline decoration-dotted'>
                  Minimum Unique Matchups Needed
                </span>
              </th>
              <th className='p-2'>Target Scheduled Games</th>
              <th className='p-2'>Available Matching Slots</th>
              <th className='p-2'>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.division_id} className='border-b'>
                <td className='p-2'>{row.division_label}</td>
                <td className='p-2'>{row.field_type_required}</td>
                <td className='p-2'>{row.number_of_teams}</td>
                <td className='p-2'>{row.minimum_unique_matchups}</td>
                <td className='p-2'>{row.target_scheduled_games ?? '—'}</td>
                <td className='p-2'>{row.available_matching_slots}</td>
                <td className='p-2'><span className={`rounded px-2 py-1 text-xs font-semibold ${statusClass(row.status)}`}>{row.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
