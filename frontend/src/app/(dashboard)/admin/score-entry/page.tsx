'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';
import { ScoreTimestamp } from '@/components/ScoreTimestamp';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

const statuses = ['MISSING','SUBMITTED','FLAGGED','CONFLICT','APPROVED','PUBLISHED','UNPUBLISHED','CORRECTION_PENDING'];

export default function CommunityScoreEntryPage() {
  const [items, setItems] = useState<any[]>([]);
  const [weeks, setWeeks] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  const [status, setStatus] = useState('');
  const [weekId, setWeekId] = useState('');
  const [drafts, setDrafts] = useState<Record<string, { home_score: string; away_score: string; notes: string }>>({});
  const { accessToken } = useAuthSession();
  const token = accessToken || undefined;
  const load = async (persistFilters = false, filters = { weekId, status }) => {
    const params = new URLSearchParams();
    if (filters.weekId) params.set('week_id', filters.weekId);
    if (filters.status) params.set('status', filters.status);
    if (persistFilters) window.history.replaceState(null, '', `${window.location.pathname}${params.size ? `?${params}` : ''}`);
    const data = await apiFetch(`/scores/my-community${params.size ? `?${params}` : ''}`, {}, token);
    setItems(data.items || []);
    setWeeks(data.weeks || []);
  };
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialFilters = { weekId: params.get('week_id') || '', status: params.get('status') || '' };
    setWeekId(initialFilters.weekId);
    setStatus(initialFilters.status);
    load(false, initialFilters).catch((error) => setMessage(error.message));
  }, []);
  const draftFor = (g: any) => drafts[g.game_id] || { home_score: g.home_score ?? '', away_score: g.away_score ?? '', notes: g.community_admin_notes || '' };
  const setDraft = (g: any, patch: Partial<{ home_score: string; away_score: string; notes: string }>) => setDrafts((current) => ({ ...current, [g.game_id]: { ...draftFor(g), ...patch } }));
  const submit = async (game: any) => {
    const d = draftFor(game);
    try {
      await apiFetch(`/scores/${game.game_id}/submit`, { method: 'PATCH', body: JSON.stringify({ home_score: String(d.home_score).trim(), away_score: String(d.away_score).trim(), community_admin_notes: d.notes }) }, token);
      setMessage('Score submitted for Scheduling Administrator approval.');
      await load();
    } catch (error: any) {
      setMessage(error?.message || 'Unable to submit score.');
    }
  };
  const flag = async (game: any) => {
    const reason = window.prompt('Describe the score issue', game.flag_reason || '') || '';
    await apiFetch(`/scores/${game.game_id}/flag`, { method: 'POST', body: JSON.stringify({ reason }) }, token);
    setMessage('Score issue flagged for Scheduling Administrator review.');
    await load();
  };
  return <div className='space-y-4'><div><h1 className='text-2xl font-bold'>Score Entry</h1><p className='text-sm text-slate-600'>Submit and manage scores for scheduled league games.</p><p className='text-xs text-slate-500'>Enter a number, leave blank for 0, or enter F for a forfeit.</p></div>{message && <div className='rounded border bg-green-50 p-3 text-sm'>{message}</div>}<div className='flex flex-wrap items-end gap-2'><label className='flex flex-col gap-1 text-sm font-medium'>Date / Week<select aria-label='Date / Week' className='rounded border p-2 font-normal' value={weekId} onChange={(e) => setWeekId(e.target.value)}><option value=''>All dates / weeks</option>{weeks.map((week) => <option key={week.id} value={week.id}>{week.label} — {formatDisplayDate(week.primary_game_date)}</option>)}</select></label><label className='flex flex-col gap-1 text-sm font-medium'>Score Status<select aria-label='Score Status' className='rounded border p-2 font-normal' value={status} onChange={(e) => setStatus(e.target.value)}><option value=''>All statuses</option>{statuses.map((s) => <option key={s}>{s}</option>)}</select></label><button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={() => load(true)}>Apply</button></div><div className='overflow-x-auto rounded border bg-white'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Date','Time','Division','Host Location','Field','Home Team','Home Score','Away Team','Away Score','Submitted By','Submitted','Score Status','Published Status','Updated','Actions'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{items.map((g) => { const locked = ['APPROVED','PUBLISHED','CONFLICT','CORRECTION_PENDING'].includes(g.score_status) || g.is_published; const d = draftFor(g); return <tr key={g.game_id} className='border-t'><td className='p-2'>{formatDisplayDate(g.game_date)}</td><td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td><td className='p-2'>{g.division_group} {g.division_name}</td><td className='p-2'>{g.host_location_name}</td><td className='p-2'>{g.field_name}</td><td className='p-2'>{g.home_team_name}</td><td className='p-2'><input className='w-20 rounded border p-1' type='text' inputMode='numeric' value={d.home_score} disabled={locked} onChange={(e) => setDraft(g, { home_score: e.target.value })} /></td><td className='p-2'>{g.away_team_name}</td><td className='p-2'><input className='w-20 rounded border p-1' type='text' inputMode='numeric' value={d.away_score} disabled={locked} onChange={(e) => setDraft(g, { away_score: e.target.value })} /></td><td className='p-2'>{g.submitted_by?.full_name || ''}</td><td className='p-2'><ScoreTimestamp value={g.submitted_at} /></td><td className='p-2'>{g.score_status}</td><td className='p-2'>{g.is_published ? 'Published' : 'Unpublished'}</td><td className='p-2'><ScoreTimestamp value={g.last_updated_at || g.submitted_at} /></td><td className='space-x-2 whitespace-nowrap p-2'>{locked ? <button className='rounded border px-2 py-1' onClick={() => flag(g)}>Flag Score Issue</button> : <button className='rounded bg-slate-800 px-2 py-1 text-white' onClick={() => submit(g)}>{g.score_status === 'SUBMITTED' || g.score_status === 'FLAGGED' ? 'Save Score' : 'Submit Score'}</button>}<span className='text-slate-500'>View Status</span></td></tr>; })}{items.length === 0 && <tr><td className='p-6 text-center text-slate-500' colSpan={15}>No score-entry games found for the selected filters.</td></tr>}</tbody></table></div></div>;
}
