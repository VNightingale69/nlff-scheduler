'use client';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

type Division = { id: string; name: string; division_group: 'COED' | 'GIRLS'; sort_order: number; required_field_layout_type: string };
type Participation = { division_id: string; team_count: number | null };

export default function DivisionParticipationManager() {
  const [orgs, setOrgs] = useState<any[]>([]);
  const [orgId, setOrgId] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [orgsLoading, setOrgsLoading] = useState(true);
  const [orgsError, setOrgsError] = useState('');
  const [divisions, setDivisions] = useState<Division[]>([]);
  const [rows, setRows] = useState<Record<string, Participation>>({});
  const [msg, setMsg] = useState('');

  const loadOrganizations = async () => {
    setOrgsLoading(true);
    setOrgsError('');
    try {
      const token = getToken();
      const orgResp = await apiFetch('/organizations', { cache: 'no-store' }, token);
      setOrgs(orgResp.items || []);
    } catch (e: any) {
      setOrgs([]);
      setOrgsError(e?.message || 'Failed to load organizations.');
    } finally { setOrgsLoading(false); }
  };

  useEffect(() => { (async () => {
    await loadOrganizations();
    const divResp = await apiFetch('/divisions?page_size=500', {}, getToken());
    setDivisions((divResp.items || []).filter((d: any) => d.is_active));
  })(); }, []);

  useEffect(() => {
    const handler = () => { loadOrganizations(); };
    window.addEventListener('organizations:changed', handler);
    return () => window.removeEventListener('organizations:changed', handler);
  }, []);

  useEffect(() => { if (!orgId) return; (async () => {
    const resp = await apiFetch(`/organization-division-participation?organization_id=${orgId}`, {}, getToken());
    const map: Record<string, Participation> = {};
    for (const d of divisions) map[d.id] = { division_id: d.id, team_count: null };
    for (const p of resp) map[p.division_id] = { division_id: p.division_id, team_count: p.team_count };
    setRows(map);
  })(); }, [orgId, divisions]);

  const groups = useMemo(() => ({
    COED: divisions.filter((d) => d.division_group === 'COED').sort((a, b) => a.sort_order - b.sort_order),
    GIRLS: divisions.filter((d) => d.division_group === 'GIRLS').sort((a, b) => a.sort_order - b.sort_order),
  }), [divisions]);

  const save = async () => {
    const items = Object.values(rows).map((row) => {
      const normalizedCount = row.team_count && row.team_count > 0 ? Math.floor(row.team_count) : 0;
      return { division_id: row.division_id, team_count: normalizedCount, is_participating: normalizedCount > 0 };
    });
    if (items.some((i) => i.team_count < 0)) return setMsg('Team count must be zero or greater.');
    await apiFetch('/organization-division-participation', { method: 'PUT', body: JSON.stringify({ organization_id: orgId, items }) }, getToken());
    setMsg('Saved participation successfully.');
  };

  const visibleOrgs = useMemo(() => orgs.filter((o) => showInactive || o.is_active !== false), [orgs, showInactive]);

  return <div className='space-y-4'>
    <h1 className='text-2xl font-bold'>Community Division Participation</h1>
    {orgsError && <p className='rounded border border-rose-200 bg-rose-50 p-2 text-sm text-rose-700'>{orgsError}</p>}
    <div className='flex items-center gap-2'>
      <select className='rounded border p-2' value={orgId} onChange={(e) => setOrgId(e.target.value)} disabled={orgsLoading || !!orgsError}>
        <option value=''>Select Organization</option>
        {visibleOrgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
      </select>
      <label className='flex items-center gap-1 text-sm'><input type='checkbox' checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Show Inactive</label>
    </div>
    {orgId && (['COED', 'GIRLS'] as const).map((g) => <div key={g} className='rounded border p-3'>
      <h2 className='mb-2 text-lg font-semibold'>{g === 'COED' ? 'Coed' : 'Girls'}</h2>
      <table className='w-full text-sm'><thead><tr className='text-left'><th>Division</th><th>Number of Teams</th><th>Participation</th></tr></thead><tbody>
        {groups[g].map((d) => {
          const teamCount = rows[d.id]?.team_count;
          const participating = (teamCount ?? 0) > 0;
          return <tr key={d.id} className='border-t'><td className='py-2'>{d.name}</td><td className='py-2'>
            <input type='number' min={0} step={1} className='w-24 rounded border p-1' value={teamCount ?? ''}
              onChange={(e) => {
                const val = e.target.value;
                const parsed = val === '' ? null : Number(val);
                setRows({ ...rows, [d.id]: { division_id: d.id, team_count: Number.isNaN(parsed) ? null : parsed } });
              }} />
          </td><td className='py-2'>{participating ? 'Participating' : 'Not participating'}</td></tr>;
        })}
      </tbody></table>
    </div>)}
    <button disabled={!orgId} className='rounded bg-emerald-700 px-4 py-2 text-white disabled:opacity-50' onClick={save}>Save Participation</button>
    {msg && <p className='text-sm text-slate-700'>{msg}</p>}
  </div>;
}
