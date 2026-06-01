'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

export default function FlaggedScoresPage() {
  const [items, setItems] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  const token = getToken() || undefined;
  const load = async () => setItems((await apiFetch('/admin/scores/flagged', {}, token)).items || []);
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  const resolve = async (game: any) => {
    const home = window.prompt('Official home score', game.home_score ?? '');
    if (home === null) return;
    const away = window.prompt('Official away score', game.away_score ?? '');
    if (away === null) return;
    const note = window.prompt('Resolution note', game.league_admin_notes ?? '') || '';
    await apiFetch(`/admin/games/${game.game_id}/score`, { method: 'PUT', body: JSON.stringify({ home_score: Number(home), away_score: Number(away), league_admin_notes: note }) }, token);
    await apiFetch(`/admin/games/${game.game_id}/score/approve`, { method: 'POST', body: JSON.stringify({ league_admin_notes: note }) }, token);
    setMessage('Flagged score resolved and approved.');
    await load();
  };
  return <div className='space-y-4'><div><h1 className='text-2xl font-bold'>Flagged Scores</h1><p className='text-sm text-slate-600'>Review outcome conflicts and finalize the official score.</p></div>{message && <div className='rounded border bg-green-50 p-3 text-sm'>{message}</div>}<div className='space-y-3'>{items.map((g) => <div key={g.game_id} className='rounded border bg-white p-4'><div className='font-semibold'>{formatDisplayDate(g.game_date)} {formatDisplayTime(g.kickoff_time)} — {g.away_team_name} at {g.home_team_name}</div><div className='text-sm text-slate-600'>{g.division_group} {g.division_name} • {g.host_location_name} • {g.field_name}</div><div className='mt-3 overflow-x-auto'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr><th className='p-2'>Away</th><th className='p-2'>Home</th><th className='p-2'>Outcome</th><th className='p-2'>Community</th><th className='p-2'>Submitted By</th><th className='p-2'>Submitted At</th><th className='p-2'>Notes</th></tr></thead><tbody>{(g.score_submissions || []).map((s: any) => <tr key={s.id} className='border-t'><td className='p-2'>{s.away_score}</td><td className='p-2'>{s.home_score}</td><td className='p-2'>{s.outcome}</td><td className='p-2'>{s.submission_source_community_name}</td><td className='p-2'>{s.submitted_by?.full_name}</td><td className='p-2'>{s.submitted_at}</td><td className='p-2'>{s.community_admin_notes}</td></tr>)}</tbody></table></div><button className='mt-3 rounded bg-slate-800 px-3 py-2 text-white' onClick={() => resolve(g)}>Resolve</button></div>)}</div>{items.length === 0 && <div className='rounded border bg-white p-4'>No flagged scores.</div>}</div>;
}
