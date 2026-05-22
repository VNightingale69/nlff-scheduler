'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

export default function GeneratedSlotsPage() {
  const token = getToken();
  const [hosts, setHosts] = useState<any[]>([]);
  const [hostId, setHostId] = useState('');
  const [slots, setSlots] = useState<any[]>([]);
  const [fieldInstances, setFieldInstances] = useState<any[]>([]);

  useEffect(() => {
    (async () => {
      const data = await apiFetch('/host-locations?page_size=500&is_active=true', {}, token);
      setHosts(data.items || []);
      if (data.items?.length) setHostId(data.items[0].id);
    })();
  }, []);

  useEffect(() => {
    if (!hostId) return;
    (async () => {
      const [slotRows, fieldRows] = await Promise.all([
        apiFetch(`/generated-game-slots?host_location_id=${hostId}`, {}, token),
        apiFetch(`/field-instances?host_location_id=${hostId}`, {}, token),
      ]);
      setSlots(slotRows || []);
      setFieldInstances(fieldRows || []);
    })();
  }, [hostId]);

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Generated Slots</h1>
      <select value={hostId} onChange={(e) => setHostId(e.target.value)} className='w-full rounded border p-2 md:w-1/2'>
        {hosts.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
      </select>
      <div className='text-sm text-slate-700'>Debug: {fieldInstances.length} field instances, {slots.length} generated slots.</div>
      <div className='overflow-auto rounded border'>
        <table className='min-w-full text-sm'>
          <thead><tr className='border-b text-left'><th className='p-2'>Date</th><th className='p-2'>Host Location</th><th className='p-2'>Field Instance</th><th className='p-2'>Field Type</th><th className='p-2'>Start Time</th><th className='p-2'>End Time</th><th className='p-2'>Status</th></tr></thead>
          <tbody>
            {slots.map((slot: any) => (
              <tr key={slot.id} className='border-b'>
                <td className='p-2'>{slot.available_date}</td>
                <td className='p-2'>{slot.host_location_name}</td>
                <td className='p-2'>{slot.field_instance_name}</td>
                <td className='p-2'>{slot.field_type}</td>
                <td className='p-2'>{slot.start_time}</td>
                <td className='p-2'>{slot.end_time}</td>
                <td className='p-2'>{slot.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
