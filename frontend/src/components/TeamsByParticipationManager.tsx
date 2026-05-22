'use client';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';

export default function TeamsByParticipationManager() {
  const [orgs, setOrgs] = useState<any[]>([]);
  const [orgId, setOrgId] = useState('');
  const [divisions, setDivisions] = useState<any[]>([]);
  const [teams, setTeams] = useState<any[]>([]);
  const [newNames, setNewNames] = useState<Record<string, string>>({});
  const [editingTeamId, setEditingTeamId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<any | null>(null);
  const [msg, setMsg] = useState('');

  const load = async (selectedOrgId: string) => {
    const token = getToken();
    const [divResp, teamResp, parts] = await Promise.all([
      apiFetch('/divisions?page_size=500', {}, token),
      apiFetch(`/teams?page_size=500&organization_id=${selectedOrgId}`, {}, token),
      apiFetch(`/organization-division-participation?organization_id=${selectedOrgId}`, {}, token),
    ]);
    const partMap = Object.fromEntries(parts.filter((p: any) => p.is_participating).map((p: any) => [p.division_id, p.team_count]));
    setDivisions((divResp.items || []).filter((d: any) => partMap[d.id] !== undefined).map((d: any) => ({ ...d, expected_count: partMap[d.id] })));
    setTeams((teamResp.items || []).filter((t: any) => t.is_active));
  };

  useEffect(() => { (async () => {
    const user = getAuthUser();
    const token = getToken();
    const orgResp = await apiFetch('/organizations?page_size=500', {}, token);
    setOrgs(orgResp.items || []);
    const initialOrg = user?.role_name === 'community_scheduler' ? user.organization_id : '';
    if (initialOrg) { setOrgId(initialOrg); load(initialOrg); }
  })(); }, []);

  const grouped = useMemo(() => Object.fromEntries(divisions.map((d) => [d.id, teams.filter((t) => t.division_id === d.id)])), [divisions, teams]);

  const addTeam = async (divisionId: string, expectedCount: number, activeCount: number) => {
    if (activeCount >= expectedCount) {
      setMsg('Team limit reached for this division.');
      return;
    }
    const name = (newNames[divisionId] || '').trim();
    if (!name) return;
    await apiFetch('/teams', { method: 'POST', body: JSON.stringify({ organization_id: orgId, division_id: divisionId, name, is_active: true }) }, getToken());
    setNewNames({ ...newNames, [divisionId]: '' });
    await load(orgId);
    setMsg('Team saved.');
  };

  const startEdit = (team: any) => {
    setEditingTeamId(team.id);
    setEditingName(team.name);
    setMsg('');
  };

  const saveEdit = async (team: any) => {
    const name = editingName.trim();
    if (!name) return;
    await apiFetch(`/teams/${team.id}`, { method: 'PATCH', body: JSON.stringify({ name }) }, getToken());
    setEditingTeamId(null);
    setEditingName('');
    await load(orgId);
    setMsg('Team updated successfully.');
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    await apiFetch(`/teams/${deleteTarget.id}`, { method: 'DELETE' }, getToken());
    setDeleteTarget(null);
    await load(orgId);
    setMsg('Team deleted successfully.');
  };

  return <div className='space-y-4'>
    <h1 className='text-2xl font-bold'>Teams</h1>
    <select className='rounded border p-2' value={orgId} onChange={(e) => { setOrgId(e.target.value); load(e.target.value); }}><option value=''>Select Organization</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
    {divisions.map((d) => {
      const existing = grouped[d.id] || [];
      const atLimit = existing.length >= d.expected_count;
      return <div key={d.id} className='rounded border p-3 space-y-2'>
        <h2 className='font-semibold'>{d.division_group === 'COED' ? 'Coed' : 'Girls'} {d.name}</h2>
        <p className='text-sm text-slate-600'>{existing.length} of {d.expected_count} teams named</p>
        <ul className='space-y-1'>
          {existing.map((t: any) => <li key={t.id} className='flex items-center gap-2'>
            {editingTeamId === t.id ? (
              <>
                <input className='rounded border p-1' value={editingName} onChange={(e) => setEditingName(e.target.value)} />
                <button className='rounded bg-emerald-700 px-2 py-1 text-white' onClick={() => saveEdit(t)}>Save</button>
                <button className='rounded border px-2 py-1' onClick={() => { setEditingTeamId(null); setEditingName(''); }}>Cancel</button>
              </>
            ) : (
              <>
                <span>{t.name}</span>
                <button className='text-sm underline' onClick={() => startEdit(t)}>Edit</button>
                <span className='text-slate-400'>|</span>
                <button className='text-sm underline text-rose-700' onClick={() => setDeleteTarget(t)}>Delete</button>
              </>
            )}
          </li>)}
        </ul>
        <div className='flex gap-2'>
          <input className='rounded border p-1' value={newNames[d.id] || ''} onChange={(e) => setNewNames({ ...newNames, [d.id]: e.target.value })} placeholder='Team Name' />
          <button disabled={atLimit} className='rounded bg-slate-700 px-3 py-1 text-white disabled:cursor-not-allowed disabled:bg-slate-400' onClick={() => addTeam(d.id, d.expected_count, existing.length)}>Add Team</button>
        </div>
        {atLimit && <p className='text-sm text-amber-700'>Team limit reached for this division.</p>}
      </div>;
    })}
    {msg && <p className='text-sm'>{msg}</p>}

    {deleteTarget && <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40'>
      <div className='w-full max-w-sm rounded bg-white p-4 shadow'>
        <p className='mb-3'>Delete team {deleteTarget.name}?</p>
        <div className='flex justify-end gap-2'>
          <button className='rounded border px-3 py-1' onClick={() => setDeleteTarget(null)}>Cancel</button>
          <button className='rounded bg-rose-700 px-3 py-1 text-white' onClick={confirmDelete}>Delete</button>
        </div>
      </div>
    </div>}
  </div>;
}
