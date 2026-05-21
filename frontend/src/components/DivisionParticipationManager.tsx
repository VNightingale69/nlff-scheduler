'use client';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

type Division = { id: string; name: string; division_group: 'COED' | 'GIRLS'; sort_order: number; required_field_layout_type: string };

type Participation = { division_id: string; is_participating: boolean; team_count: number };

export default function DivisionParticipationManager() {
  const [orgs, setOrgs] = useState<any[]>([]);
  const [orgId, setOrgId] = useState('');
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [rows, setRows] = useState<Record<string, Participation>>({});
  const [msg, setMsg] = useState('');

  useEffect(() => { (async () => {
    const token = getToken();
    const [orgResp, divResp] = await Promise.all([apiFetch('/organizations?page_size=500', {}, token), apiFetch('/divisions?page_size=500', {}, token)]);
    setOrgs(orgResp.items || []);
    setDivisions((divResp.items || []).filter((d: any) => d.is_active));
  })(); }, []);

  useEffect(() => { if (!orgId) return; (async () => {
    const token = getToken();
    const resp = await apiFetch(`/organization-division-participation?organization_id=${orgId}`, {}, token);
    const map: Record<string, Participation> = {};
    for (const d of divisions) map[d.id] = { division_id: d.id, is_participating: false, team_count: 0 };
    for (const p of resp) map[p.division_id] = { division_id: p.division_id, is_participating: p.is_participating, team_count: p.team_count };
    setRows(map);
  })(); }, [orgId, divisions]);

  const groups = useMemo(() => ({
    COED: divisions.filter((d) => d.division_group === 'COED').sort((a, b) => a.sort_order - b.sort_order),
    GIRLS: divisions.filter((d) => d.division_group === 'GIRLS').sort((a, b) => a.sort_order - b.sort_order),
  }), [divisions]);

  const save = async () => {
    const items = Object.values(rows);
    for (const i of items) {
      if (i.team_count < 0) return setMsg('Team count must be zero or greater.');
      if (i.is_participating && i.team_count < 1) return setMsg('Participating divisions must have at least 1 team.');
    }
    await apiFetch('/organization-division-participation', { method: 'PUT', body: JSON.stringify({ organization_id: orgId, items }) }, getToken());
    setMsg('Saved participation successfully.');
  };

  return <div className='space-y-4'>
    <h1 className='text-2xl font-bold'>Community Division Participation</h1>
    <select className='rounded border p-2' value={orgId} onChange={(e) => setOrgId(e.target.value)}><option value=''>Select Organization</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
    {orgId && (['COED', 'GIRLS'] as const).map((g) => <div key={g} className='rounded border p-3'><h2 className='mb-2 text-lg font-semibold'>{g === 'COED' ? 'Coed' : 'Girls'}</h2><div className='space-y-2'>{groups[g].map((d) => <div key={d.id} className='flex items-center gap-3'><span className='w-40'>{d.name}</span><label className='flex items-center gap-1'><input type='checkbox' checked={rows[d.id]?.is_participating || false} onChange={(e) => setRows({ ...rows, [d.id]: { ...rows[d.id], division_id: d.id, is_participating: e.target.checked } })} /> Participating</label><input type='number' min={0} className='w-24 rounded border p-1' value={rows[d.id]?.team_count ?? 0} onChange={(e) => setRows({ ...rows, [d.id]: { ...rows[d.id], division_id: d.id, team_count: Number(e.target.value), is_participating: rows[d.id]?.is_participating ?? false } })} /></div>)}</div></div>)}
    <button disabled={!orgId} className='rounded bg-emerald-700 px-4 py-2 text-white disabled:opacity-50' onClick={save}>Save Participation</button>
    {msg && <p className='text-sm text-slate-700'>{msg}</p>}
  </div>;
}
