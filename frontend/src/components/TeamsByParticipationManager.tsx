'use client';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken, getUser } from '@/lib/auth';

export default function TeamsByParticipationManager() {
  const [orgs, setOrgs] = useState<any[]>([]);
  const [orgId, setOrgId] = useState('');
  const [divisions, setDivisions] = useState<any[]>([]);
  const [teams, setTeams] = useState<any[]>([]);
  const [newNames, setNewNames] = useState<Record<string, string>>({});
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
    setTeams(teamResp.items || []);
  };

  useEffect(() => { (async () => {
    const user = getUser();
    const token = getToken();
    const orgResp = await apiFetch('/organizations?page_size=500', {}, token);
    setOrgs(orgResp.items || []);
    const initialOrg = user?.role_name === 'community_scheduler' ? user.organization_id : '';
    if (initialOrg) { setOrgId(initialOrg); load(initialOrg); }
  })(); }, []);

  const grouped = useMemo(() => Object.fromEntries(divisions.map((d) => [d.id, teams.filter((t) => t.division_id === d.id)])), [divisions, teams]);

  const addTeam = async (divisionId: string) => {
    const name = (newNames[divisionId] || '').trim();
    if (!name) return;
    await apiFetch('/teams', { method: 'POST', body: JSON.stringify({ organization_id: orgId, division_id: divisionId, name, is_active: true }) }, getToken());
    setNewNames({ ...newNames, [divisionId]: '' });
    await load(orgId);
    setMsg('Team saved.');
  };

  return <div className='space-y-4'>
    <h1 className='text-2xl font-bold'>Teams</h1>
    <select className='rounded border p-2' value={orgId} onChange={(e) => { setOrgId(e.target.value); load(e.target.value); }}><option value=''>Select Organization</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
    {divisions.map((d) => { const existing = grouped[d.id] || []; return <div key={d.id} className='rounded border p-3 space-y-2'><h2 className='font-semibold'>{d.division_group === 'COED' ? 'Coed' : 'Girls'} {d.name}</h2><p className='text-sm text-slate-600'>{existing.length} of {d.expected_count} teams named</p><ul className='list-disc pl-5'>{existing.map((t: any) => <li key={t.id}>{t.name}</li>)}</ul><div className='flex gap-2'><input className='rounded border p-1' value={newNames[d.id] || ''} onChange={(e) => setNewNames({ ...newNames, [d.id]: e.target.value })} placeholder='Team Name' /><button className='rounded bg-slate-700 px-3 py-1 text-white' onClick={() => addTeam(d.id)}>Add Team</button></div></div>; })}
    {msg && <p className='text-sm'>{msg}</p>}
  </div>;
}
