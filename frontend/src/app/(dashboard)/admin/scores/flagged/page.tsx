'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

export default function FlaggedScoresPage() {
  const [items, setItems] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  const { accessToken } = useAuthSession();
  const token = accessToken || undefined;
  const load = async () => setItems((await apiFetch('/admin/scores/flagged', {}, token)).items || []);
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  const resolve = async (game: any) => {
    const home = window.prompt('Official home score', game.home_score ?? '');
    if (home === null) return;
    const away = window.prompt('Official away score', game.away_score ?? '');
    if (away === null) return;
    const note = window.prompt('Resolution note', game.league_admin_notes ?? '') || '';
    await apiFetch(`/scores/${game.game_id}/resolve-conflict`, { method: 'POST', body: JSON.stringify({ home_score: String(home).trim(), away_score: String(away).trim(), league_admin_notes: note }) }, token);
    setMessage('Flagged score resolved and approved.');
    await load();
  };
  return <div className='space-y-4'><div><h1 className='text-2xl font-bold'>Flagged Scores</h1><p className='text-sm text-slate-600'>Review flagged score issues, conflicts, disputes, unpublished corrections, and correction-pending scores.</p></div>{message && <div className='rounded border bg-green-50 p-3 text-sm'>{message}</div>}<div className='space-y-3'>{items.map((g) => <div key={g.game_id} className='rounded border bg-white p-4'><div className='font-semibold'>{formatDisplayDate(g.game_date)} {formatDisplayTime(g.kickoff_time)} — {g.away_team_name} at {g.home_team_name}</div><div className='text-sm text-slate-600'>{g.division_group} {g.division_name} • {g.host_location_name} • {g.field_name} • {g.score_status} • {g.is_published ? 'Published' : 'Unpublished'}</div>{g.flag_reason && <div className='mt-2 rounded bg-amber-50 p-2 text-sm'>Flag reason: {g.flag_reason}</div>}<div className='mt-3 overflow-x-auto'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr><th className='p-2'>Away</th><th className='p-2'>Home</th><th className='p-2'>Outcome</th><th className='p-2'>Community</th><th className='p-2'>Submitted By</th><th className='p-2'>Submitted At</th><th className='p-2'>Notes</th></tr></thead><tbody>{(g.score_submissions || []).map((s: any) => <tr key={s.id} className='border-t'><td className='p-2'>{s.away_score}</td><td className='p-2'>{s.home_score}</td><td className='p-2'>{s.outcome}</td><td className='p-2'>{s.submission_source_community_name}</td><td className='p-2'>{s.submitted_by?.full_name}</td><td className='p-2'>{s.submitted_at}</td><td className='p-2'>{s.community_admin_notes}</td></tr>)}</tbody></table></div><button className='mt-3 rounded bg-slate-800 px-3 py-2 text-white' onClick={() => resolve(g)}>Resolve</button></div>)}</div>{items.length === 0 && <div className='rounded border bg-white p-4'>No flagged scores.</div>}</div>;
}
