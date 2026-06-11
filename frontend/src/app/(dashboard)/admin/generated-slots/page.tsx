'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';
import { formatDisplayDate, formatDisplayTime, formatDisplayTimestamp } from '@/lib/displayFormat';

export default function GeneratedSlotsPage() {
  const { accessToken: token } = useAuthSession();
  const searchParams = useSearchParams();
  const startDate = searchParams.get('start_date') || '';
  const endDate = searchParams.get('end_date') || '';
  const [hosts, setHosts] = useState<any[]>([]);
  const [seasons, setSeasons] = useState<any[]>([]);
  const [seasonId, setSeasonId] = useState('');
  const [hostId, setHostId] = useState('');
  const [slots, setSlots] = useState<any[]>([]);
  const [fieldInstances, setFieldInstances] = useState<any[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [lastGeneratedAt, setLastGeneratedAt] = useState<string | null>(null);

  const loadHostData = async (selectedHostId: string) => {
    if (!selectedHostId) return;
    const [slotRows, fieldRows]: any = await Promise.all([
      apiFetch(`/generated-game-slots?host_location_id=${selectedHostId}`, {}, token),
      apiFetch(`/field-instances?host_location_id=${selectedHostId}`, {}, token),
    ]);
    setSlots(slotRows || []);
    setFieldInstances(fieldRows || []);
  };

  useEffect(() => {
    (async () => {
      const [hostData, optionData]: any = await Promise.all([
        apiFetch('/host-locations?page_size=500&is_active=true', {}, token),
        apiFetch('/manual-schedule-builder/options', {}, token),
      ]);
      setHosts(hostData.items || []);
      if (hostData.items?.length) setHostId(hostData.items[0].id);
      setSeasons(optionData.seasons || []);
      const activeSeason = optionData.seasons?.find((season: any) => season.is_active) || optionData.seasons?.[0];
      if (activeSeason?.id) setSeasonId(activeSeason.id);
    })();
  }, []);

  useEffect(() => {
    if (!hostId) return;
    (async () => {
      await loadHostData(hostId);
    })();
  }, [hostId]);

  const visibleSlots = useMemo(() => slots.filter((slot: any) => (!startDate || slot.available_date >= startDate) && (!endDate || slot.available_date <= endDate)), [slots, startDate, endDate]);

  const onGenerate = async () => {
    setIsGenerating(true);
    setMessage('Generating...');
    setError('');
    try {
      const response: any = await apiFetch('/generated-game-slots/regenerate', { method: 'POST', body: JSON.stringify({ season_id: seasonId || null }) }, token);
      const lockedSkipped = Number(response?.total_locked_slots_skipped || 0);
      setMessage(
        lockedSkipped > 0
          ? `Skipped ${lockedSkipped} locked slots already assigned to scheduled games.`
          : (response?.message || 'Slots generated successfully'),
      );
      setResults(response?.results || []);
      setLastGeneratedAt(response?.last_generated_at || new Date().toISOString());
      if (hostId) {
        await loadHostData(hostId);
      }
    } catch (e: any) {
      const detail = e?.message || 'Failed to generate slots';
      setError(detail);
      setMessage('');
    } finally {
      setIsGenerating(false);
    }
  };

  const onClear = async () => {
    if (!hostId) {
      setError('Select a host location before clearing slots.');
      setMessage('');
      return;
    }

    const confirmed = window.confirm('Clear generated slots for this host location? This will remove unassigned generated slots. Slots or field instances referenced by scheduled games will be preserved.');
    if (!confirmed) return;

    setIsClearing(true);
    setMessage('Clearing slots...');
    setError('');
    try {
      const response: any = await apiFetch(`/generated-game-slots?host_location_id=${encodeURIComponent(hostId)}`, { method: 'DELETE' }, token);
      const warning = response?.warning ? ` ${response.warning}` : '';
      setMessage(`Cleared ${response?.slots_deleted ?? 0} generated slots and ${response?.field_instances_deleted ?? 0} field instances. Preserved ${response?.field_instances_preserved ?? 0} field instances and ${response?.games_preserved ?? 0} scheduled games.${warning}`);
      setResults([]);
      await loadHostData(hostId);
    } catch (e: any) {
      const detail = e?.message || 'Failed to clear slots';
      setError(detail);
      setMessage('');
    } finally {
      setIsClearing(false);
    }
  };

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Generated Slots</h1>
      <div className='grid gap-3 md:grid-cols-2'>
        <label className='text-sm font-medium'>
          Host preview
          <select value={hostId} onChange={(e) => setHostId(e.target.value)} className='mt-1 w-full rounded border p-2'>
            {hosts.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        </label>
        <label className='text-sm font-medium'>
          Season for league-wide regeneration
          <select value={seasonId} onChange={(e) => setSeasonId(e.target.value)} className='mt-1 w-full rounded border p-2'>
            {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
      </div>
      <div className='flex items-center gap-3'>
        <button onClick={onGenerate} disabled={isGenerating || isClearing || !seasonId} className='rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-60'>
          {isGenerating ? 'Generating...' : 'League-wide Regenerate Slots'}
        </button>
        <button onClick={onClear} disabled={!hostId || isGenerating || isClearing} className='rounded bg-red-600 px-4 py-2 text-white disabled:opacity-60'>
          {isClearing ? 'Clearing...' : 'Clear Slots'}
        </button>
        {lastGeneratedAt ? <span className='text-sm text-slate-600'>Last Generated: {formatDisplayTimestamp(lastGeneratedAt)}</span> : null}
      </div>
      {message ? <div className='rounded border border-green-200 bg-green-50 p-2 text-sm text-green-700'>{message}</div> : null}
      {error ? <div className='rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700'>{error}</div> : null}
      {startDate || endDate ? <div className='rounded border bg-blue-50 p-2 text-sm text-blue-800'>Filtered to week date range: {formatDisplayDate(startDate)} – {formatDisplayDate(endDate)}</div> : null}
      <div className='text-sm text-slate-700'>Debug: {fieldInstances.length} field instances, {visibleSlots.length} generated slots.</div>
      {results.length > 0 ? (
        <div className='rounded border p-3 text-sm'>
          <h2 className='mb-2 font-semibold'>Generation Summary</h2>
          <div className='space-y-2'>
            {results.map((row: any) => (
              <div key={row.host_location_id}>
                <div className='font-medium'>{row.host_location_name}</div>
                <div>- total slots evaluated: {row.total_slots_evaluated ?? 0}</div>
                <div>- slots regenerated: {row.slots_regenerated ?? 0}</div>
                <div>- locked slots skipped: {row.locked_slots_skipped ?? 0}</div>
                <div>- new slots created: {row.new_slots_created ?? 0}</div>
                <div>- obsolete unused slots removed: {row.obsolete_unused_slots_removed ?? 0}</div>
                <div>- hard failures: {row.hard_failures ?? 0}</div>
                <div>- {row.field_instances_created} field instances created</div>
                <div>- {row.slots_created} slots generated</div>
                {row.skipped_reason ? <div>- {row.skipped_reason}</div> : null}
                {row.errors?.length ? <div>- Errors: {Array.from(new Set(row.errors as string[])).join('; ')}</div> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className='overflow-auto rounded border'>
        <table className='min-w-full text-sm'>
          <thead><tr className='border-b text-left'><th className='p-2'>Date</th><th className='p-2'>Host Location</th><th className='p-2'>Field Instance</th><th className='p-2'>Field Type</th><th className='p-2'>Start Time</th><th className='p-2'>End Time</th><th className='p-2'>Status</th></tr></thead>
          <tbody>
            {visibleSlots.map((slot: any) => (
              <tr key={slot.id} className='border-b'>
                <td className='p-2'>{formatDisplayDate(slot.available_date)}</td>
                <td className='p-2'>{slot.host_location_name}</td>
                <td className='p-2'>{slot.field_instance_name}</td>
                <td className='p-2'>{slot.field_type}</td>
                <td className='p-2'>{formatDisplayTime(slot.start_time)}</td>
                <td className='p-2'>{formatDisplayTime(slot.end_time)}</td>
                <td className='p-2'>{slot.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
