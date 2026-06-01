'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

export default function CommunityScoreEntryPage() {
  const [items, setItems] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  const [status, setStatus] = useState('');
  const token = getToken() || undefined;
  const load = async () => {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    setItems((await apiFetch(`/community/scores${query}`, {}, token)).items || []);
  };
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  const submit = async (game: any) => {
    const homeInput = document.getElementById(`home-${game.game_id}`) as HTMLInputElement | null;
    const awayInput = document.getElementById(`away-${game.game_id}`) as HTMLInputElement | null;
    const notesInput = document.getElementById(`notes-${game.game_id}`) as HTMLInputElement | null;
    await apiFetch(`/community/games/${game.game_id}/score`, { method: 'POST', body: JSON.stringify({ home_score: Number(homeInput?.value), away_score: Number(awayInput?.value), community_admin_notes: notesInput?.value || '' }) }, token);
    setMessage('Score submitted for League Admin approval.');
    await load();
  };
  return <div className='space-y-4'><div><h1 className='text-2xl font-bold'>Score Entry</h1><p className='text-sm text-slate-600'>Submit scores only for scheduled games involving your community.</p></div>{message && <div className='rounded border bg-green-50 p-3 text-sm'>{message}</div>}<div className='flex gap-2'><select className='rounded border p-2' value={status} onChange={(e) => setStatus(e.target.value)}><option value=''>All statuses</option><option>SCHEDULED</option><option>SCORE_PENDING</option><option>SUBMITTED</option><option>FLAGGED</option><option>APPROVED</option></select><button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={load}>Apply</button></div><div className='overflow-x-auto rounded border bg-white'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Date','Time','Division','Location','Field','Away Team','Home Team','Status','Away Score','Home Score','Notes','Action'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{items.map((g) => { const locked = g.score_status === 'FLAGGED' || g.score_status === 'APPROVED'; return <tr key={g.game_id} className='border-t'><td className='p-2'>{formatDisplayDate(g.game_date)}</td><td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td><td className='p-2'>{g.division_group} {g.division_name}</td><td className='p-2'>{g.host_location_name}</td><td className='p-2'>{g.field_name}</td><td className='p-2'>{g.away_team_name}</td><td className='p-2'>{g.home_team_name}</td><td className='p-2'>{g.score_status}{g.score_status === 'FLAGGED' ? ' — League Admin review required' : ''}</td><td className='p-2'><input id={`away-${g.game_id}`} className='w-20 rounded border p-1' type='number' min='0' defaultValue={g.away_score ?? ''} disabled={locked} /></td><td className='p-2'><input id={`home-${g.game_id}`} className='w-20 rounded border p-1' type='number' min='0' defaultValue={g.home_score ?? ''} disabled={locked} /></td><td className='p-2'><input id={`notes-${g.game_id}`} className='rounded border p-1' defaultValue={g.community_admin_notes || ''} disabled={locked} /></td><td className='p-2'>{locked ? <span className='text-slate-500'>{g.score_status === 'APPROVED' ? 'Final score' : 'Read only'}</span> : <button className='rounded bg-slate-800 px-2 py-1 text-white' onClick={() => submit(g)}>Submit Score</button>}</td></tr>; })}</tbody></table></div></div>;
}
