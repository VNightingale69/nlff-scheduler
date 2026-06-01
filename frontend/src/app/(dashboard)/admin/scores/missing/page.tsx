'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

export default function MissingScoresPage() {
  const [items, setItems] = useState<any[]>([]);
  const [message, setMessage] = useState('');
  useEffect(() => { apiFetch('/admin/scores/missing', {}, getToken() || undefined).then((data) => setItems(data.items || [])).catch((error) => setMessage(error.message)); }, []);
  return <div className='space-y-4'><div><h1 className='text-2xl font-bold'>Missing Scores</h1><p className='text-sm text-slate-600'>Past scheduled games that do not have an approved official score.</p></div>{message && <div className='rounded border bg-red-50 p-3 text-sm'>{message}</div>}<div className='overflow-x-auto rounded border bg-white'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Date','Time','Division','Location','Field','Away Team','Home Team','Host Community','Status','Submitter'].map((h) => <th key={h} className='p-2'>{h}</th>)}</tr></thead><tbody>{items.map((g) => <tr key={g.game_id} className='border-t'><td className='p-2'>{formatDisplayDate(g.game_date)}</td><td className='p-2'>{formatDisplayTime(g.kickoff_time)}</td><td className='p-2'>{g.division_group} {g.division_name}</td><td className='p-2'>{g.host_location_name}</td><td className='p-2'>{g.field_name}</td><td className='p-2'>{g.away_team_name}</td><td className='p-2'>{g.home_team_name}</td><td className='p-2'>{g.host_community_name || ''}</td><td className='p-2'>{g.score_status}</td><td className='p-2'>{g.submitted_by?.full_name || ''}</td></tr>)}</tbody></table></div></div>;
}
