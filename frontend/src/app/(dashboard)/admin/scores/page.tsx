'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

type ScoreGame = any;
const statuses = ['MISSING','SUBMITTED','FLAGGED','CONFLICT','APPROVED','PUBLISHED','UNPUBLISHED','CORRECTION_PENDING'];

export default function ScoreManagementPage() {
  const [items, setItems] = useState<ScoreGame[]>([]);
  const [filters, setFilters] = useState({ date: '', division_id: '', organization_id: '', host_location_id: '', status: '', published: '', missing: false, flagged: false, conflicts: false });
  const [drafts, setDrafts] = useState<Record<string, { home_score: string; away_score: string; notes: string }>>({});
  const [message, setMessage] = useState('');
  const token = getToken() || undefined;

  const query = () => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (typeof value === 'boolean') { if (value) params.set(key, 'true'); return; }
      if (value) params.set(key, value);
    });
    const text = params.toString();
    return text ? `?${text}` : '';
  };
  const load = async () => {
    const data = await apiFetch(`/scores${query()}`, {}, token);
    setItems(data.items || []);
  };
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);

  const draftFor = (g: ScoreGame) => drafts[g.game_id] || { home_score: g.home_score ?? '', away_score: g.away_score ?? '', notes: g.league_admin_notes || '' };
  const setDraft = (g: ScoreGame, patch: Partial<{ home_score: string; away_score: string; notes: string }>) => setDrafts((current) => ({ ...current, [g.game_id]: { ...draftFor(g), ...patch } }));
  const payloadFor = (g: ScoreGame) => { const d = draftFor(g); return { home_score: String(d.home_score).trim(), away_score: String(d.away_score).trim(), league_admin_notes: d.notes }; };
  const act = async (label: string, path: string, options: RequestInit = {}) => { try { await apiFetch(path, options, token); setMessage(label); await load(); } catch (error: any) { setMessage(error?.message || 'Unable to save score.'); } };
  const save = (g: ScoreGame) => act('Score correction saved.', `/scores/${g.game_id}`, { method: 'PATCH', body: JSON.stringify(payloadFor(g)) });
  const approve = (g: ScoreGame) => act('Score approved.', `/scores/${g.game_id}/approve`, { method: 'POST', body: JSON.stringify({ league_admin_notes: draftFor(g).notes }) });
  const publish = (g: ScoreGame) => act('Score published.', `/scores/${g.game_id}/publish`, { method: 'POST' });
  const approvePublish = (g: ScoreGame) => act('Score approved and published.', `/scores/${g.game_id}/approve-and-publish`, { method: 'POST', body: JSON.stringify({ league_admin_notes: draftFor(g).notes }) });
  const unpublish = async (g: ScoreGame) => { const reason = window.prompt('Unpublish reason', g.unpublished_reason || '') || ''; await act('Score unpublished.', `/scores/${g.game_id}/unpublish`, { method: 'POST', body: JSON.stringify({ reason }) }); };
  const clear = async (g: ScoreGame) => { if (!window.confirm('Clear this score?')) return; await act('Score cleared.', `/scores/${g.game_id}/clear`, { method: 'POST', body: JSON.stringify({ reason: 'Cleared from Score Management' }) }); };
  const resolve = (g: ScoreGame) => act('Conflict resolved and approved.', `/scores/${g.game_id}/resolve-conflict`, { method: 'POST', body: JSON.stringify(payloadFor(g)) });
  const flag = async (g: ScoreGame) => { const reason = window.prompt('Flag reason', g.flag_reason || '') || ''; await act('Score flagged.', `/scores/${g.game_id}/flag`, { method: 'POST', body: JSON.stringify({ reason }) }); };
  const history = async (g: ScoreGame) => { const data = await apiFetch(`/scores/${g.game_id}/history`, {}, token); alert((data.items || []).map((h: any) => `${h.created_at}: ${h.action} ${h.previous_away_score ?? ''}-${h.previous_home_score ?? ''} → ${h.new_away_score ?? ''}-${h.new_home_score ?? ''} (${h.previous_status} → ${h.new_status}) by ${h.actor?.full_name || h.actor_user_id || 'system'}${h.reason ? ` — ${h.reason}` : ''}`).join('\n') || 'No score history yet.'); };

  return <div className='space-y-4'>
    <div><h1 className='text-2xl font-bold'>Score Management</h1><p className='text-sm text-slate-600'>Inline review, correction, approval, publishing, unpublishing, and audit for scores tied to scheduled games.</p><p className='text-xs text-slate-500'>Enter a number, leave blank for 0, or enter F for a forfeit.</p></div>
    {message && <div className='rounded border bg-green-50 p-3 text-sm'>{message}</div>}
    <div className='grid gap-2 rounded border bg-white p-3 md:grid-cols-4'>
      <input className='rounded border p-2' type='date' value={filters.date} onChange={(e) => setFilters({ ...filters, date: e.target.value })} />
      <input className='rounded border p-2' placeholder='Division ID' value={filters.division_id} onChange={(e) => setFilters({ ...filters, division_id: e.target.value })} />
      <input className='rounded border p-2' placeholder='Community ID' value={filters.organization_id} onChange={(e) => setFilters({ ...filters, organization_id: e.target.value })} />
      <input className='rounded border p-2' placeholder='Host Location ID' value={filters.host_location_id} onChange={(e) => setFilters({ ...filters, host_location_id: e.target.value })} />
      <select className='rounded border p-2' value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value=''>All score statuses</option>{statuses.map((s) => <option key={s}>{s}</option>)}</select>
      <select className='rounded border p-2' value={filters.published} onChange={(e) => setFilters({ ...filters, published: e.target.value })}><option value=''>All published states</option><option value='published'>Published</option><option value='unpublished'>Unpublished</option></select>
      {(['missing','flagged','conflicts'] as const).map((key) => <label key={key} className='flex items-center gap-2 text-sm'><input type='checkbox' checked={filters[key]} onChange={(e) => setFilters({ ...filters, [key]: e.target.checked })} /> {key === 'missing' ? 'Missing Scores' : key === 'flagged' ? 'Flagged Scores' : 'Conflicts'}</label>)}
      <button className='rounded bg-slate-800 px-3 py-2 text-white' onClick={load}>Apply Filters</button>
    </div>
    <div className='overflow-x-auto rounded border bg-white'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Date','Time','Division','Host Location','Field','Home Team','Away Team','Home Score','Away Score','Submitted By','Submitted At','Score Status','Published Status','Last Updated','Actions'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{items.map((g) => { const d = draftFor(g); return <tr key={g.game_id} className='border-t align-top'><td className='p-2'>{formatDisplayDate(g.game_date)}</td><td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td><td className='p-2'>{g.division_group} {g.division_name}</td><td className='p-2'>{g.host_location_name}</td><td className='p-2'>{g.field_name}</td><td className='p-2'>{g.home_team_name}</td><td className='p-2'>{g.away_team_name}</td><td className='p-2'><input className='w-20 rounded border p-1' type='text' inputMode='numeric' value={d.home_score} onChange={(e) => setDraft(g, { home_score: e.target.value })} /></td><td className='p-2'><input className='w-20 rounded border p-1' type='text' inputMode='numeric' value={d.away_score} onChange={(e) => setDraft(g, { away_score: e.target.value })} /></td><td className='p-2'>{g.submitted_by?.full_name || ''}</td><td className='p-2'>{g.submitted_at || ''}</td><td className='p-2'>{g.score_status}</td><td className='p-2'>{g.is_published ? 'Published' : 'Unpublished'}</td><td className='p-2'>{g.last_updated_at || g.approved_at || g.submitted_at || ''}</td><td className='flex flex-wrap gap-1 p-2'><button className='rounded border px-2 py-1' onClick={() => save(g)}>Save Correction</button><button className='rounded border px-2 py-1' onClick={() => approve(g)}>Approve</button><button className='rounded border px-2 py-1' onClick={() => publish(g)}>Publish</button><button className='rounded border px-2 py-1' onClick={() => approvePublish(g)}>Approve & Publish</button><button className='rounded border px-2 py-1' onClick={() => unpublish(g)}>Unpublish</button><button className='rounded border px-2 py-1' onClick={() => resolve(g)}>Resolve Conflict</button><button className='rounded border px-2 py-1' onClick={() => flag(g)}>Flag</button><button className='rounded border px-2 py-1' onClick={() => clear(g)}>Clear Score</button><button className='rounded border px-2 py-1' onClick={() => history(g)}>View History</button></td></tr>; })}</tbody></table></div>
  </div>;
}
