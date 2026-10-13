'use client';
import { useState } from 'react';
import { apiFetch } from '@/lib/api';
type Preview = { rows_uploaded: number; valid_games: number; invalid_rows: number; skipped_rows: number; fingerprint: string; is_published: boolean; rows: { row: number; division: string; csv_game_id: string; game_number?: number; matched_round?: string; skipped?: boolean; date?: string; time?: string; site?: string; field?: string; errors: string[] }[] };
export default function TournamentScheduleImport({ tournamentId, token, onApplied }: { tournamentId: string; token?: string; onApplied: (tournament: any) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [skipResets, setSkipResets] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const submit = async (apply: boolean) => {
    if (!file) return;
    setBusy(true); setMessage('');
    try {
      const body = new FormData(); body.append('file', file);
      const query = `?skip_resets=${skipResets}${apply ? `&apply=true&fingerprint=${encodeURIComponent(preview?.fingerprint || '')}` : ''}`;
      const result = await apiFetch(`/tournaments/${tournamentId}/schedule-import${query}`, { method: 'POST', body }, token);
      if (apply) { onApplied(result.tournament); setPreview(null); setConfirmed(false); setMessage(`Assigned schedules to ${result.updated_games} tournament games.`); }
      else { setPreview(result.preview); setConfirmed(false); }
    } catch (error: unknown) { setPreview(null); setConfirmed(false); setMessage(error instanceof Error ? error.message : 'Unable to import tournament schedule.'); }
    finally { setBusy(false); }
  };
  return <section className='space-y-3 rounded border bg-slate-50 p-3'>
    <h4 className='font-semibold'>Import Tournament Schedule</h4>
    <p className='text-sm'>CSV columns: Date, Time, Division, Game ID, Round, Host Location, Field, Home Team, Away Team. Matches use teams and feeder games, not CSV numbering. Import updates existing game assignments and preserves seeds, results, and publication.</p>
    <label className='flex items-center gap-2 text-sm'><input type='checkbox' disabled={busy} checked={skipResets} onChange={e => { setSkipResets(e.target.checked); setPreview(null); setConfirmed(false); }} />Exclude conditional/reset games (one championship final, no reset)</label>
    <input aria-label='Tournament schedule CSV' type='file' accept='.csv' disabled={busy} onChange={e => { setFile(e.target.files?.[0] || null); setPreview(null); setConfirmed(false); setMessage(''); }} />
    <button className='rounded border bg-white px-3 py-2 disabled:opacity-50' disabled={!file || busy} onClick={() => submit(false)}>{busy ? 'Working…' : 'Validate and Preview'}</button>
    {message && <p role='status'>{message}</p>}
    {preview && <><p>{preview.rows_uploaded} rows · {preview.valid_games} valid · {preview.invalid_rows} with errors · {preview.skipped_rows} reset games excluded. No changes applied.</p>
      <div className='max-h-96 overflow-auto'><table className='min-w-full text-left text-xs'><thead><tr>{['Row', 'Division', 'CSV Game', 'Bracket Game', 'Date / Time', 'Location / Field', 'Validation'].map(h => <th className='p-2' key={h}>{h}</th>)}</tr></thead><tbody>{preview.rows.map(row => <tr className='border-t' key={row.row}><td className='p-2'>{row.row}</td><td className='p-2'>{row.division}</td><td className='p-2'>{row.csv_game_id}</td><td className='p-2'>{row.game_number ?? '—'} {row.matched_round}</td><td className='p-2'>{row.date} {row.time}</td><td className='p-2'>{row.site} / {row.field}</td><td className={`p-2 ${row.errors.length ? 'text-red-700' : 'text-green-800'}`}>{row.skipped ? 'Excluded: no-reset rule' : row.errors.join(' ') || 'Ready'}</td></tr>)}</tbody></table></div>
      {preview.invalid_rows === 0 && preview.valid_games > 0 && <><label className='flex items-center gap-2 text-sm'><input type='checkbox' checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={busy} />Replace these {preview.valid_games} games’ assignments{preview.is_published ? '; this will change the published tournament schedule' : ''}.</label><button className='rounded bg-green-700 px-3 py-2 text-white disabled:opacity-50' disabled={!confirmed || busy} onClick={() => submit(true)}>Apply Tournament Schedule</button></>}
    </>}
  </section>;
}
