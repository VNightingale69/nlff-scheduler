'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

type ScoreGame = any;

export default function ScoreManagementPage() {
  const [items, setItems] = useState<ScoreGame[]>([]);
  const [status, setStatus] = useState('');
  const [message, setMessage] = useState('');
  const token = getToken() || undefined;

  const load = async () => {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    const data = await apiFetch(`/admin/scores${query}`, {}, token);
    setItems(data.items || []);
  };

  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);

  const saveScore = async (game: ScoreGame) => {
    const home = window.prompt('Home score', game.score_display_home ?? game.home_score ?? '');
    if (home === null) return;
    const away = window.prompt('Away score', game.score_display_away ?? game.away_score ?? '');
    if (away === null) return;
    const notes = window.prompt('League notes', game.league_admin_notes ?? '') || '';
    await apiFetch(`/admin/games/${game.game_id}/score`, { method: 'PUT', body: JSON.stringify({ home_score: home, away_score: away, league_admin_notes: notes }) }, token);
    setMessage('Score saved. Approve it to publish the final result.');
    await load();
  };

  const approve = async (game: ScoreGame) => {
    await apiFetch(`/admin/games/${game.game_id}/score/approve`, { method: 'POST', body: JSON.stringify({ league_admin_notes: game.league_admin_notes || '' }) }, token);
    setMessage('Score approved and published.');
    await load();
  };

  const unpublish = async (game: ScoreGame) => {
    await apiFetch(`/admin/games/${game.game_id}/score/unpublish`, { method: 'POST', body: JSON.stringify({ league_admin_notes: game.league_admin_notes || '' }) }, token);
    setMessage('Score unpublished. It is no longer visible on the public schedule.');
    await load();
  };

  const history = async (game: ScoreGame) => {
    const data = await apiFetch(`/admin/games/${game.game_id}/score-history`, {}, token);
    alert((data.items || []).map((s: any) => `${s.submitted_at}: ${s.score_display_away ?? s.away_score}-${s.score_display_home ?? s.home_score} by ${s.submitted_by?.full_name || s.submitted_by_user_id}${s.normalization_note ? ` (${s.normalization_note})` : ''}`).join('\n') || 'No score submissions yet.');
  };

  return <div className='space-y-4'><div><h1 className='text-2xl font-bold'>Score Management</h1><p className='text-sm text-slate-600'>Enter, edit, override, approve, and review scores tied to scheduled games.</p></div>{message && <div className='rounded border bg-green-50 p-3 text-sm'>{message}</div>}<div className='flex gap-2'><select className='rounded border p-2' value={status} onChange={(e) => setStatus(e.target.value)}><option value=''>All statuses</option><option>SCHEDULED</option><option>SCORE_PENDING</option><option>SUBMITTED</option><option>FLAGGED</option><option>APPROVED</option></select><button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={load}>Apply</button></div><div className='overflow-x-auto rounded border bg-white'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Date','Time','Division','Location','Field','Away Team','Home Team','Away Score','Home Score','Status','Submitted By','Submitted At','Approved By','Approved At','Community Notes','League Notes','Actions'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{items.map((g) => <tr key={g.game_id} className='border-t'><td className='p-2'>{formatDisplayDate(g.game_date)}</td><td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td><td className='p-2'>{g.division_group} {g.division_name}</td><td className='p-2'>{g.host_location_name}</td><td className='p-2'>{g.field_name}</td><td className='p-2'>{g.away_team_name}</td><td className='p-2'>{g.home_team_name}</td><td className='p-2'>{g.score_display_away ?? g.away_score ?? ''}</td><td className='p-2'>{g.score_display_home ?? g.home_score ?? ''}</td><td className='p-2'>{g.score_status}</td><td className='p-2'>{g.submitted_by?.full_name || ''}</td><td className='p-2'>{g.submitted_at || ''}</td><td className='p-2'>{g.approved_by?.full_name || ''}</td><td className='p-2'>{g.approved_at || ''}</td><td className='p-2'>{g.community_admin_notes || ''}</td><td className='p-2'>{g.league_admin_notes || ''}</td><td className='space-x-2 whitespace-nowrap p-2'><button className='rounded border px-2 py-1' onClick={() => saveScore(g)}>Edit</button><button className='rounded border px-2 py-1' disabled={g.home_score == null || g.away_score == null} onClick={() => approve(g)}>Approve</button><button className='rounded border px-2 py-1' disabled={g.score_status !== 'APPROVED'} onClick={() => unpublish(g)}>Unpublish</button><button className='rounded border px-2 py-1' onClick={() => history(g)}>History</button></td></tr>)}</tbody></table></div></div>;
}
