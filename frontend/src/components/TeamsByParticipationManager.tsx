'use client';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';

type FieldType = 'SMALL' | 'LARGE';

const DIVISION_SORT_ORDER = ['K/1st', '2nd/3rd', '4th/5th', '6th/7th', '8th'];

const resolveDivisionLabel = (division: any) => `${division.division_group === 'COED' ? 'Coed' : 'Girls'} ${division.name}`;

const resolveFieldType = (division: any): FieldType => {
  const divisionName = String(division?.name || '').trim();
  const group = String(division?.division_group || '').toUpperCase();
  if (group === 'COED') {
    return ['K/1st', '2nd/3rd', '4th/5th'].includes(divisionName) ? 'SMALL' : 'LARGE';
  }
  if (group === 'GIRLS') {
    return ['K/1st', '2nd/3rd', '4th/5th'].includes(divisionName) ? 'SMALL' : 'LARGE';
  }
  return 'LARGE';
};

const divisionSortRank = (division: any) => {
  const group = String(division?.division_group || '').toUpperCase();
  const idx = DIVISION_SORT_ORDER.indexOf(String(division?.name || ''));
  const orderWithinGroup = idx === -1 ? 99 : idx;
  return `${group === 'COED' ? '0' : '1'}-${String(orderWithinGroup).padStart(2, '0')}`;
};

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

  const loadLeagueSummary = async () => {
    const token = getToken();
    const [divResp, teamResp] = await Promise.all([
      apiFetch('/divisions?page_size=500', {}, token),
      apiFetch('/teams?page_size=500', {}, token),
    ]);
    setDivisions(divResp.items || []);
    setTeams((teamResp.items || []).filter((t: any) => t.is_active));
  };

  useEffect(() => { (async () => {
    const user = getAuthUser();
    const token = getToken();
    const orgResp = await apiFetch('/organizations?page_size=500', {}, token);
    setOrgs((orgResp.items || []).filter((o: any) => o.is_active));
    const initialOrg = user?.role_name === 'community_scheduler' ? user.organization_id : '';
    if (initialOrg) { setOrgId(initialOrg); load(initialOrg); }
    else { loadLeagueSummary(); }
  })(); }, []);

  const grouped = useMemo(() => Object.fromEntries(divisions.map((d) => [d.id, teams.filter((t) => t.division_id === d.id)])), [divisions, teams]);

  const leagueSummary = useMemo(() => {
    const divisionsById = Object.fromEntries(divisions.map((d: any) => [d.id, d]));
    const coedTeams = teams.filter((t: any) => divisionsById[t.division_id]?.division_group === 'COED').length;
    const girlsTeams = teams.filter((t: any) => divisionsById[t.division_id]?.division_group === 'GIRLS').length;
    const smallFieldTeams = teams.filter((t: any) => resolveFieldType(divisionsById[t.division_id]) === 'SMALL').length;
    const largeFieldTeams = teams.filter((t: any) => resolveFieldType(divisionsById[t.division_id]) === 'LARGE').length;
    return {
      totalOrganizations: orgs.length,
      totalTeams: teams.length,
      totalCoedTeams: coedTeams,
      totalGirlsTeams: girlsTeams,
      smallFieldTeams,
      largeFieldTeams,
    };
  }, [divisions, teams, orgs]);

  const leagueTableRows = useMemo(() => {
    const divisionsById = Object.fromEntries(divisions.map((d: any) => [d.id, d]));
    const orgById = Object.fromEntries(orgs.map((o: any) => [o.id, o.name]));
    const rowMap = new Map<string, any>();
    teams.forEach((team: any) => {
      const div = divisionsById[team.division_id];
      if (!div) return;
      const key = `${div.id}::${team.organization_id}`;
      if (!rowMap.has(key)) {
        rowMap.set(key, {
          divisionLabel: resolveDivisionLabel(div),
          divisionSort: divisionSortRank(div),
          organizationName: orgById[team.organization_id] || 'Unknown',
          teamCount: 0,
          teamNames: [],
          fieldType: resolveFieldType(div),
        });
      }
      const row = rowMap.get(key);
      row.teamCount += 1;
      row.teamNames.push(team.name);
    });

    return Array.from(rowMap.values()).sort((a, b) => {
      if (a.divisionSort !== b.divisionSort) return a.divisionSort.localeCompare(b.divisionSort);
      return a.organizationName.localeCompare(b.organizationName);
    });
  }, [divisions, teams, orgs]);

  const quickIndicators = useMemo(() => {
    const oddRows = leagueTableRows.filter((row) => row.teamCount % 2 === 1);
    const doubleHeaderDivisions = Array.from(new Set(oddRows.map((row) => row.divisionLabel)));
    return { oddRows, doubleHeaderDivisions };
  }, [leagueTableRows]);

  const addTeam = async (divisionId: string, expectedCount: number, activeCount: number) => {
    if (activeCount >= expectedCount) return;
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
    <select className='rounded border p-2' value={orgId} onChange={(e) => { const value = e.target.value; setOrgId(value); if (value) load(value); else loadLeagueSummary(); }}><option value=''>League-wide view</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>

    {!orgId && <>
      <div className='grid grid-cols-1 gap-3 md:grid-cols-3'>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total organizations</div><div className='text-xl font-semibold'>{leagueSummary.totalOrganizations}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total teams</div><div className='text-xl font-semibold'>{leagueSummary.totalTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total coed teams</div><div className='text-xl font-semibold'>{leagueSummary.totalCoedTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total girls teams</div><div className='text-xl font-semibold'>{leagueSummary.totalGirlsTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Small-field teams</div><div className='text-xl font-semibold'>{leagueSummary.smallFieldTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Large-field teams</div><div className='text-xl font-semibold'>{leagueSummary.largeFieldTeams}</div></div>
      </div>

      <div className='rounded border bg-amber-50 p-3 text-sm'>
        <div><span className='font-semibold'>Odd team count warnings:</span> {quickIndicators.oddRows.length === 0 ? 'None' : `${quickIndicators.oddRows.length} organization/division group(s)`}</div>
        <div><span className='font-semibold'>Divisions requiring weekly double headers:</span> {quickIndicators.doubleHeaderDivisions.length === 0 ? 'None' : quickIndicators.doubleHeaderDivisions.join(', ')}</div>
      </div>

      <div className='overflow-x-auto rounded border bg-white'>
        <table className='w-full text-left text-sm'>
          <thead className='bg-slate-100'>
            <tr>
              <th className='p-2'>Division</th>
              <th className='p-2'>Organization/Community</th>
              <th className='p-2'>Team Count</th>
              <th className='p-2'>Team Names</th>
              <th className='p-2'>Field Type Requirement</th>
            </tr>
          </thead>
          <tbody>
            {leagueTableRows.map((row, idx) => <tr key={`${row.divisionLabel}-${row.organizationName}-${idx}`} className='border-t'>
              <td className='p-2'>{row.divisionLabel}</td>
              <td className='p-2'>{row.organizationName}</td>
              <td className='p-2'>{row.teamCount}{row.teamCount % 2 === 1 ? <span className='ml-2 text-amber-700'>⚠ odd</span> : null}</td>
              <td className='p-2'>{row.teamNames.sort((a: string, b: string) => a.localeCompare(b)).join(', ')}</td>
              <td className='p-2'>{row.fieldType}</td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </>}

    {orgId && divisions.map((d) => {
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
          <input disabled={atLimit} className='rounded border p-1 disabled:cursor-not-allowed disabled:bg-slate-100' value={newNames[d.id] || ''} onChange={(e) => setNewNames({ ...newNames, [d.id]: e.target.value })} placeholder='Team Name' />
          <button disabled={atLimit} className='rounded bg-slate-700 px-3 py-1 text-white disabled:cursor-not-allowed disabled:bg-slate-400' onClick={() => addTeam(d.id, d.expected_count, existing.length)}>Add Team</button>
        </div>
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
