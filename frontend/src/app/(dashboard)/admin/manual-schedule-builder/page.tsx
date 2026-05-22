'use client';

import { useEffect, useMemo, useState } from 'react';
import { ApiError, apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

export default function ManualScheduleBuilderPage() {
  const token = getToken();
  const [options, setOptions] = useState<any>({ divisions: [], teams: [], host_locations: [] });
  const [divisionId, setDivisionId] = useState('');
  const [homeTeamId, setHomeTeamId] = useState('');
  const [awayTeamId, setAwayTeamId] = useState('');
  const [slotId, setSlotId] = useState('');
  const [slots, setSlots] = useState<any[]>([]);
  const [games, setGames] = useState<any[]>([]);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const division = useMemo(() => options.divisions.find((d: any) => d.id === divisionId), [options, divisionId]);
  const divisionTeams = useMemo(() => options.teams.filter((t: any) => t.division_id === divisionId && t.is_active), [options, divisionId]);
  const canSave = Boolean(homeTeamId && awayTeamId && slotId);

  const extractError = (e: unknown) => {
    if (e instanceof ApiError && e.details && typeof e.details === 'object') {
      const detail = (e.details as any).detail;
      if (Array.isArray(detail)) return detail.map((x: any) => x?.msg || JSON.stringify(x)).join('; ');
      if (typeof detail === 'string') return detail;
      if (detail && typeof detail === 'object') return JSON.stringify(detail);
      return e.message;
    }
    return e instanceof Error ? e.message : 'Request failed.';
  };

  const load = async () => {
    const opts: any = await apiFetch('/manual-schedule-builder/options', {}, token);
    setOptions(opts);
    if (!divisionId && opts.divisions?.length) setDivisionId(opts.divisions[0].id);
    const scheduled: any = await apiFetch('/games?page_size=300', {}, token);
    setGames(scheduled.items || []);
  };

  useEffect(() => {
    load().catch((e) => setError(extractError(e)));
  }, []);

  useEffect(() => {
    if (!division?.required_field_type) return;
    apiFetch(`/generated-game-slots?status=OPEN&field_type=${division.required_field_type}`, {}, token)
      .then((r: any) => setSlots(r || []))
      .catch((e: unknown) => setError(extractError(e)));
  }, [division?.required_field_type]);

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Manual Schedule Builder</h1>
      {error ? <div className='rounded border border-red-200 bg-red-50 p-2 text-red-700'>{error}</div> : null}
      {success ? <div className='rounded border border-emerald-200 bg-emerald-50 p-2 text-emerald-700'>{success}</div> : null}

      <div className='grid gap-2 md:grid-cols-4'>
        <select className='rounded border p-2' value={divisionId} onChange={(e) => setDivisionId(e.target.value)}>
          <option value=''>Division</option>
          {options.divisions.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select className='rounded border p-2' value={homeTeamId} onChange={(e) => setHomeTeamId(e.target.value)}>
          <option value=''>Home Team</option>
          {divisionTeams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select className='rounded border p-2' value={awayTeamId} onChange={(e) => setAwayTeamId(e.target.value)}>
          <option value=''>Away Team</option>
          {divisionTeams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <button
          className='rounded bg-blue-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300'
          disabled={!canSave}
          onClick={async () => {
            setError('');
            setSuccess('');
            try {
              await apiFetch('/manual-schedule-builder/assign', { method: 'POST', body: JSON.stringify({ division_id: divisionId, home_team_id: homeTeamId, away_team_id: awayTeamId, generated_slot_id: slotId }) }, token);
              await load();
              setSlotId('');
              setSuccess('Game successfully scheduled.');
            } catch (e: unknown) {
              setError(extractError(e));
            }
          }}
        >
          Save Game Assignment
        </button>
      </div>

      <div className='overflow-auto rounded border'>
        <table className='min-w-full border-separate border-spacing-y-1 text-sm'>
          <thead>
            <tr>
              {['Date', 'Host Location', 'Field', 'Field Type', 'Start', 'End', 'Select'].map((h) => (
                <th key={h} className='px-2 py-2 text-center font-bold'>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slots.map((s: any) => (
              <tr key={s.id} className={`align-middle ${slotId === s.id ? 'bg-blue-50' : 'bg-white'}`}>
                <td className='px-2 py-3 text-center'>{s.available_date}</td>
                <td className='px-2 py-3 text-center'>{s.host_location_name}</td>
                <td className='px-2 py-3 text-center'>{s.field_instance_name}</td>
                <td className='px-2 py-3 text-center'>{s.field_type}</td>
                <td className='px-2 py-3 text-center'>{s.start_time}</td>
                <td className='px-2 py-3 text-center'>{s.end_time}</td>
                <td className='px-2 py-3 text-center'><input type='radio' checked={slotId === s.id} onChange={() => setSlotId(s.id)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className='overflow-auto rounded border'>
        <table className='min-w-full text-sm'>
          <thead><tr><th>Date</th><th>Time</th><th>Division</th><th>Home</th><th>Away</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{games.map((g: any) => <tr key={g.id}><td>{g.game_date}</td><td>{g.kickoff_time}</td><td>{options.divisions.find((d: any) => d.id === g.division_id)?.name || '-'}</td><td>{options.teams.find((t: any) => t.id === g.home_team_id)?.name || '-'}</td><td>{options.teams.find((t: any) => t.id === g.away_team_id)?.name || '-'}</td><td>{g.status_code}</td><td><button className='text-red-600 underline' onClick={async () => { await apiFetch(`/games/${g.id}`, { method: 'DELETE' }, token); await load(); }}>Delete / Unschedule</button></td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
