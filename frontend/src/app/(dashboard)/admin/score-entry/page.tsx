'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

const statuses = ['MISSING','SUBMITTED','FLAGGED','CONFLICT','APPROVED','PUBLISHED','UNPUBLISHED','CORRECTION_PENDING'];

export default function CommunityScoreEntryPage() {
  const [items, setItems] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  const [status, setStatus] = useState('');
  const [drafts, setDrafts] = useState<Record<string, { home_score: string; away_score: string; notes: string }>>({});
  const token = getToken() || undefined;
  const load = async () => {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    setItems((await apiFetch(`/scores/my-community${query}`, {}, token)).items || []);
  };
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  const draftFor = (g: any) => drafts[g.game_id] || { home_score: g.home_score ?? '', away_score: g.away_score ?? '', notes: g.community_admin_notes || '' };
  const setDraft = (g: any, patch: Partial<{ home_score: string; away_score: string; notes: string }>) => setDrafts((current) => ({ ...current, [g.game_id]: { ...draftFor(g), ...patch } }));
  const submit = async (game: any) => {
    const d = draftFor(game);
    await apiFetch(`/scores/${game.game_id}/submit`, { method: 'PATCH', body: JSON.stringify({ home_score: Number(d.home_score), away_score: Number(d.away_score), community_admin_notes: d.notes }) }, token);
    setMessage('Score submitted for Scheduling Administrator approval.');
    await load();
  };
  const flag = async (game: any) => {
    const reason = window.prompt('Describe the score issue', game.flag_reason || '') || '';
    await apiFetch(`/scores/${game.game_id}/flag`, { method: 'POST', body: JSON.stringify({ reason }) }, token);
    setMessage('Score issue flagged for Scheduling Administrator review.');
    await load();
  };
  return <div className='space-y-4'><div><h1 className='text-2xl font-bold'>Score Entry</h1><p className='text-sm text-slate-600'>Submit scores inline for scheduled games involving your community as either the home or away team.</p></div>{message && <div className='rounded border bg-green-50 p-3 text-sm'>{message}</div>}<div className='flex gap-2'><select className='rounded border p-2' value={status} onChange={(e) => setStatus(e.target.value)}><option value=''>All statuses</option>{statuses.map((s) => <option key={s}>{s}</option>)}</select><button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={load}>Apply</button></div><div className='overflow-x-auto rounded border bg-white'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Date','Time','Division','Host Location','Field','Home Team','Away Team','Home Score','Away Score','Submitted By','Submitted At','Score Status','Published Status','Last Updated','Actions'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{items.map((g) => { const locked = ['APPROVED','PUBLISHED','CONFLICT','CORRECTION_PENDING'].includes(g.score_status) || g.is_published; const d = draftFor(g); return <tr key={g.game_id} className='border-t'><td className='p-2'>{formatDisplayDate(g.game_date)}</td><td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td><td className='p-2'>{g.division_group} {g.division_name}</td><td className='p-2'>{g.host_location_name}</td><td className='p-2'>{g.field_name}</td><td className='p-2'>{g.home_team_name}</td><td className='p-2'>{g.away_team_name}</td><td className='p-2'><input className='w-20 rounded border p-1' type='number' min='0' value={d.home_score} disabled={locked} onChange={(e) => setDraft(g, { home_score: e.target.value })} /></td><td className='p-2'><input className='w-20 rounded border p-1' type='number' min='0' value={d.away_score} disabled={locked} onChange={(e) => setDraft(g, { away_score: e.target.value })} /></td><td className='p-2'>{g.submitted_by?.full_name || ''}</td><td className='p-2'>{g.submitted_at || ''}</td><td className='p-2'>{g.score_status}</td><td className='p-2'>{g.is_published ? 'Published' : 'Unpublished'}</td><td className='p-2'>{g.last_updated_at || g.submitted_at || ''}</td><td className='space-x-2 whitespace-nowrap p-2'>{locked ? <button className='rounded border px-2 py-1' onClick={() => flag(g)}>Flag Score Issue</button> : <button className='rounded bg-slate-800 px-2 py-1 text-white' onClick={() => submit(g)}>{g.score_status === 'SUBMITTED' || g.score_status === 'FLAGGED' ? 'Save Score' : 'Submit Score'}</button>}<span className='text-slate-500'>View Status</span></td></tr>; })}</tbody></table></div></div>;
}
