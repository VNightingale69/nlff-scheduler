'use client';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, apiFetch } from '@/lib/api';
import { getAuthUser, getToken, type AuthUser } from '@/lib/auth';

type FieldType = 'SMALL' | 'MEDIUM' | 'LARGE';
type TeamFormState = { name: string; is_active: boolean };

const DIVISION_SORT_ORDER = ['K-1', '2-3', '4-5', '6-7', '8', 'K-2', '3-5', '6-8'];

const resolveDivisionLabel = (division: any) => `${division.division_group === 'COED' ? 'Coed' : 'Girls'} ${division.name}`;

const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  SMALL: 'Small',
  MEDIUM: 'Medium',
  LARGE: 'Large',
};

const resolveFieldType = (division: any): FieldType => {
  const divisionName = String(division?.name || '').trim();
  const group = String(division?.division_group || '').toUpperCase();
  if (group === 'COED') {
    if (['K-1', '2-3'].includes(divisionName)) return 'SMALL';
    if (divisionName === '4-5') return 'MEDIUM';
    return 'LARGE';
  }
  if (group === 'GIRLS') {
    if (divisionName === 'K-2') return 'SMALL';
    if (divisionName === '3-5') return 'MEDIUM';
    return 'LARGE';
  }
  return 'LARGE';
};

const calculateWeeklyDemand = (teamCount: number) => Math.ceil(teamCount / 2);

const divisionSortRank = (division: any) => {
  const group = String(division?.division_group || '').toUpperCase();
  const idx = DIVISION_SORT_ORDER.indexOf(String(division?.name || ''));
  const orderWithinGroup = idx === -1 ? 99 : idx;
  return `${group === 'COED' ? '0' : '1'}-${String(orderWithinGroup).padStart(2, '0')}`;
};

const getErrorMessage = (error: unknown) => error instanceof ApiError ? error.message : 'Request failed. Please try again.';

export default function TeamsByParticipationManager() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [orgs, setOrgs] = useState<any[]>([]);
  const [orgId, setOrgId] = useState('');
  const [divisions, setDivisions] = useState<any[]>([]);
  const [teams, setTeams] = useState<any[]>([]);
  const [newTeams, setNewTeams] = useState<Record<string, TeamFormState>>({});
  const [editingTeamId, setEditingTeamId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [editingIsActive, setEditingIsActive] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<any | null>(null);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const isCommunityAdmin = user?.role_name === 'COMMUNITY_ADMIN';
  const selectedOrg = useMemo(() => orgs.find((o) => o.id === orgId), [orgId, orgs]);

  const load = async (selectedOrgId: string, options: { showLoading?: boolean } = {}) => {
    if (!selectedOrgId) return;
    if (options.showLoading) setLoading(true);
    setError('');
    try {
      const token = getToken();
      const [divResp, teamResp, parts] = await Promise.all([
        apiFetch('/divisions?page_size=500', {}, token),
        apiFetch(`/teams?page_size=500&organization_id=${selectedOrgId}`, {}, token),
        apiFetch(`/organization-division-participation?organization_id=${selectedOrgId}`, {}, token),
      ]);
      const activeDivisions = (divResp.items || []).filter((d: any) => d.is_active);
      const participatingParts = (parts || []).filter((p: any) => p.is_participating);
      const partMap = Object.fromEntries(participatingParts.map((p: any) => [p.division_id, p.team_count]));
      const visibleDivisions = participatingParts.length > 0
        ? activeDivisions.filter((d: any) => partMap[d.id] !== undefined).map((d: any) => ({ ...d, expected_count: partMap[d.id] }))
        : activeDivisions.map((d: any) => ({ ...d, expected_count: null }));
      setDivisions(visibleDivisions);
      setTeams(teamResp.items || []);
    } catch (err) {
      setError(getErrorMessage(err));
      setDivisions([]);
      setTeams([]);
    } finally {
      if (options.showLoading) setLoading(false);
    }
  };

  const loadLeagueSummary = async (options: { showLoading?: boolean } = {}) => {
    if (options.showLoading) setLoading(true);
    setError('');
    try {
      const token = getToken();
      const [divResp, teamResp] = await Promise.all([
        apiFetch('/divisions?page_size=500', {}, token),
        apiFetch('/teams?page_size=500', {}, token),
      ]);
      setDivisions((divResp.items || []).filter((d: any) => d.is_active));
      setTeams(teamResp.items || []);
    } catch (err) {
      setError(getErrorMessage(err));
      setDivisions([]);
      setTeams([]);
    } finally {
      if (options.showLoading) setLoading(false);
    }
  };

  useEffect(() => { (async () => {
    setLoading(true);
    setError('');
    const authUser = getAuthUser();
    setUser(authUser);
    const token = getToken();
    try {
      const orgResp = await apiFetch('/organizations?page_size=500', {}, token);
      const activeOrgs = (orgResp.items || []).filter((o: any) => o.is_active);
      setOrgs(activeOrgs);
      const initialOrg = authUser?.role_name === 'COMMUNITY_ADMIN' ? authUser.organization_id || '' : '';
      setOrgId(initialOrg);
      if (initialOrg) await load(initialOrg);
      else await loadLeagueSummary();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  })(); }, []);

  const grouped = useMemo(() => Object.fromEntries(divisions.map((d) => [d.id, teams.filter((t) => t.division_id === d.id)])), [divisions, teams]);
  const activeTeams = useMemo(() => teams.filter((t: any) => t.is_active), [teams]);

  const leagueSummary = useMemo(() => {
    const divisionsById = Object.fromEntries(divisions.map((d: any) => [d.id, d]));
    const coedTeams = activeTeams.filter((t: any) => divisionsById[t.division_id]?.division_group === 'COED').length;
    const girlsTeams = activeTeams.filter((t: any) => divisionsById[t.division_id]?.division_group === 'GIRLS').length;
    const smallFieldTeams = activeTeams.filter((t: any) => resolveFieldType(divisionsById[t.division_id]) === 'SMALL').length;
    const mediumFieldTeams = activeTeams.filter((t: any) => resolveFieldType(divisionsById[t.division_id]) === 'MEDIUM').length;
    const largeFieldTeams = activeTeams.filter((t: any) => resolveFieldType(divisionsById[t.division_id]) === 'LARGE').length;
    return { totalOrganizations: orgs.length, totalTeams: activeTeams.length, totalCoedTeams: coedTeams, totalGirlsTeams: girlsTeams, smallFieldTeams, mediumFieldTeams, largeFieldTeams };
  }, [divisions, activeTeams, orgs]);

  const leagueTableRows = useMemo(() => {
    const divisionsById = Object.fromEntries(divisions.map((d: any) => [d.id, d]));
    const orgById = Object.fromEntries(orgs.map((o: any) => [o.id, o.name]));
    const rowMap = new Map<string, any>();
    activeTeams.forEach((team: any) => {
      const div = divisionsById[team.division_id];
      if (!div) return;
      const key = `${div.id}::${team.organization_id}`;
      if (!rowMap.has(key)) rowMap.set(key, { divisionLabel: resolveDivisionLabel(div), divisionSort: divisionSortRank(div), organizationName: orgById[team.organization_id] || 'Unknown', teamCount: 0, teamNames: [], fieldType: resolveFieldType(div) });
      const row = rowMap.get(key);
      row.teamCount += 1;
      row.teamNames.push(team.name);
    });
    return Array.from(rowMap.values()).sort((a, b) => a.divisionSort !== b.divisionSort ? a.divisionSort.localeCompare(b.divisionSort) : a.organizationName.localeCompare(b.organizationName));
  }, [divisions, activeTeams, orgs]);

  const divisionDemandRows = useMemo(() => {
    const divisionsById = Object.fromEntries(divisions.map((d: any) => [d.id, d]));
    const rowMap = new Map<string, any>();
    activeTeams.forEach((team: any) => {
      const div = divisionsById[team.division_id];
      if (!div) return;
      if (!rowMap.has(div.id)) rowMap.set(div.id, { divisionLabel: resolveDivisionLabel(div), divisionSort: divisionSortRank(div), fieldType: resolveFieldType(div), teamCount: 0 });
      rowMap.get(div.id).teamCount += 1;
    });
    return Array.from(rowMap.values()).sort((a, b) => a.divisionSort.localeCompare(b.divisionSort));
  }, [divisions, activeTeams]);

  const schedulingDemand = useMemo(() => divisionDemandRows.reduce((acc, row) => {
    acc[row.fieldType as FieldType] += calculateWeeklyDemand(row.teamCount);
    return acc;
  }, { SMALL: 0, MEDIUM: 0, LARGE: 0 } as Record<FieldType, number>), [divisionDemandRows]);

  const refreshSelectedOrg = async () => {
    if (orgId) await load(orgId);
    else await loadLeagueSummary();
  };

  const addTeam = async (divisionId: string, expectedCount: number | null, activeCount: number) => {
    if (expectedCount !== null && activeCount >= expectedCount) return;
    const form = newTeams[divisionId] || { name: '', is_active: true };
    const name = form.name.trim();
    if (!name) {
      setError('Team name is required.');
      return;
    }
    setSaving(true);
    setError('');
    setMsg('');
    try {
      await apiFetch('/teams', { method: 'POST', body: JSON.stringify({ organization_id: orgId, division_id: divisionId, name, is_active: form.is_active }) }, getToken());
      setNewTeams({ ...newTeams, [divisionId]: { name: '', is_active: true } });
      await load(orgId);
      setMsg('Team saved.');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const startEdit = (team: any) => {
    setEditingTeamId(team.id);
    setEditingName(team.name);
    setEditingIsActive(team.is_active);
    setMsg('');
    setError('');
  };

  const saveEdit = async (team: any) => {
    const name = editingName.trim();
    if (!name) {
      setError('Team name is required.');
      return;
    }
    setSaving(true);
    setError('');
    setMsg('');
    try {
      await apiFetch(`/teams/${team.id}`, { method: 'PATCH', body: JSON.stringify({ name, is_active: editingIsActive }) }, getToken());
      setEditingTeamId(null);
      setEditingName('');
      await refreshSelectedOrg();
      setMsg('Team updated successfully.');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setSaving(true);
    setError('');
    setMsg('');
    try {
      await apiFetch(`/teams/${deleteTarget.id}`, { method: 'DELETE' }, getToken());
      setDeleteTarget(null);
      await refreshSelectedOrg();
      setMsg('Team deleted successfully.');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return <div className='space-y-4'>
    <h1 className='text-2xl font-bold'>Teams</h1>

    {isCommunityAdmin ? <div className='rounded border bg-white p-3'>
      <div className='text-xs font-semibold uppercase tracking-wide text-slate-500'>Assigned community</div>
      <div className='text-lg font-semibold'>{selectedOrg?.name || 'Loading assigned community...'}</div>
      <p className='text-sm text-slate-600'>You can only manage teams for this community.</p>
    </div> : <select className='rounded border p-2' value={orgId} onChange={async (e) => { const value = e.target.value; setOrgId(value); setMsg(''); if (value) await load(value, { showLoading: true }); else await loadLeagueSummary({ showLoading: true }); }}>
      <option value=''>League-wide view</option>{orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
    </select>}

    {loading && <p className='rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700'>Loading teams...</p>}
    {error && <p className='rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800'>{error}</p>}
    {msg && <p className='rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800'>{msg}</p>}

    {!loading && !orgId && <>
      <div className='grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-4'>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total Organizations</div><div className='text-xl font-semibold'>{leagueSummary.totalOrganizations}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total Teams</div><div className='text-xl font-semibold'>{leagueSummary.totalTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total Coed Teams</div><div className='text-xl font-semibold'>{leagueSummary.totalCoedTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Total Girls Teams</div><div className='text-xl font-semibold'>{leagueSummary.totalGirlsTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Small Field Teams</div><div className='text-xl font-semibold'>{leagueSummary.smallFieldTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Medium Field Teams</div><div className='text-xl font-semibold'>{leagueSummary.mediumFieldTeams}</div></div>
        <div className='rounded border bg-white p-3'><div className='text-xs text-slate-500'>Large Field Teams</div><div className='text-xl font-semibold'>{leagueSummary.largeFieldTeams}</div></div>
      </div>

      <div className='grid grid-cols-1 gap-3 md:grid-cols-3'>
        <div className='rounded border bg-sky-50 p-3'><div className='text-xs text-slate-500'>Small Field Demand</div><div className='text-xl font-semibold'>{schedulingDemand.SMALL}</div><div className='text-xs text-slate-500'>weekly game slot(s)</div></div>
        <div className='rounded border bg-sky-50 p-3'><div className='text-xs text-slate-500'>Medium Field Demand</div><div className='text-xl font-semibold'>{schedulingDemand.MEDIUM}</div><div className='text-xs text-slate-500'>weekly game slot(s)</div></div>
        <div className='rounded border bg-sky-50 p-3'><div className='text-xs text-slate-500'>Large Field Demand</div><div className='text-xl font-semibold'>{schedulingDemand.LARGE}</div><div className='text-xs text-slate-500'>weekly game slot(s)</div></div>
      </div>

      <div className='overflow-x-auto rounded border bg-white'>
        <div className='border-b bg-slate-50 p-3'>
          <h2 className='font-semibold'>Divisions Requiring Weekly Doubleheaders</h2>
          <p className='text-xs text-slate-600'>Odd team counts are supported by scheduling logic; they require one weekly doubleheader game within that division.</p>
        </div>
        <table className='w-full text-left text-sm'>
          <thead className='bg-slate-100'><tr><th className='p-2'>Division Name</th><th className='p-2'>Team Count</th><th className='p-2'>Doubleheader Required</th></tr></thead>
          <tbody>{divisionDemandRows.length === 0 ? <tr><td className='p-2 text-slate-500' colSpan={3}>No active teams found.</td></tr> : divisionDemandRows.map((row) => <tr key={row.divisionLabel} className='border-t'><td className='p-2'>{row.divisionLabel}</td><td className='p-2'>{row.teamCount}</td><td className='p-2'>{row.teamCount % 2 === 1 ? 'Yes' : 'No'}</td></tr>)}</tbody>
        </table>
      </div>

      <div className='overflow-x-auto rounded border bg-white'>
        <table className='w-full text-left text-sm'>
          <thead className='bg-slate-100'><tr><th className='p-2'>Division</th><th className='p-2'>Organization/Community</th><th className='p-2'>Team Count</th><th className='p-2'>Team Names</th><th className='p-2'>Field Type Requirement</th></tr></thead>
          <tbody>{leagueTableRows.length === 0 ? <tr><td className='p-2 text-slate-500' colSpan={5}>No active teams found.</td></tr> : leagueTableRows.map((row, idx) => <tr key={`${row.divisionLabel}-${row.organizationName}-${idx}`} className='border-t'><td className='p-2'>{row.divisionLabel}</td><td className='p-2'>{row.organizationName}</td><td className='p-2'>{row.teamCount}</td><td className='p-2'>{row.teamNames.sort((a: string, b: string) => a.localeCompare(b)).join(', ')}</td><td className='p-2'>{FIELD_TYPE_LABELS[row.fieldType as FieldType]}</td></tr>)}</tbody>
        </table>
      </div>
    </>}

    {!loading && orgId && <>
      <div className='rounded border bg-slate-50 p-3 text-sm text-slate-700'>
        Managing teams for <span className='font-semibold'>{selectedOrg?.name || 'selected community'}</span>.
      </div>
      <div className='rounded border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900'>
        <div className='mb-1 font-semibold'>Team naming guidance</div>
        <p>When creating teams, use a consistent team name that includes the community name, division/grade level, and a differentiator such as a color. Examples: Westosha Coed K/1 Maroon, Westosha Coed K/1 Silver.</p>
      </div>
      {teams.length === 0 && <p className='rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900'>No teams have been added for this community.</p>}
      {divisions.length === 0 && !error && <p className='rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700'>No active divisions are available for team setup.</p>}
      {divisions.map((d) => {
        const existing = grouped[d.id] || [];
        const activeExisting = existing.filter((t: any) => t.is_active);
        const expectedCount = d.expected_count as number | null;
        const atLimit = expectedCount !== null && activeExisting.length >= expectedCount;
        const form = newTeams[d.id] || { name: '', is_active: true };
        return <div key={d.id} className='space-y-3 rounded border bg-white p-3'>
          <div className='flex flex-wrap items-start justify-between gap-2'>
            <div>
              <h2 className='font-semibold'>{resolveDivisionLabel(d)}</h2>
              <p className='text-sm text-slate-600'>{expectedCount === null ? `${activeExisting.length} active team(s)` : `${activeExisting.length} of ${expectedCount} active teams named`} · {FIELD_TYPE_LABELS[resolveFieldType(d)]} field</p>
            </div>
          </div>
          <div className='overflow-x-auto rounded border'>
            <table className='w-full text-left text-sm'>
              <thead className='bg-slate-100'><tr><th className='p-2'>Team name</th><th className='p-2'>Division / grade level</th><th className='p-2'>Active status</th><th className='p-2'>Actions</th></tr></thead>
              <tbody>{existing.length === 0 ? <tr><td className='p-2 text-slate-500' colSpan={4}>No teams have been added for this division.</td></tr> : existing.map((t: any) => <tr key={t.id} className='border-t'>
                {editingTeamId === t.id ? <>
                  <td className='p-2'><input className='w-full rounded border p-1' value={editingName} onChange={(e) => setEditingName(e.target.value)} /></td>
                  <td className='p-2'>{resolveDivisionLabel(d)}</td>
                  <td className='p-2'><label className='flex items-center gap-2'><input type='checkbox' checked={editingIsActive} onChange={(e) => setEditingIsActive(e.target.checked)} /> Active</label></td>
                  <td className='space-x-2 p-2'><button disabled={saving} className='rounded bg-emerald-700 px-2 py-1 text-white disabled:bg-slate-400' onClick={() => saveEdit(t)}>Save</button><button className='rounded border px-2 py-1' onClick={() => { setEditingTeamId(null); setEditingName(''); }}>Cancel</button></td>
                </> : <>
                  <td className='p-2'>{t.name}</td>
                  <td className='p-2'>{resolveDivisionLabel(d)}</td>
                  <td className='p-2'>{t.is_active ? 'Active' : 'Inactive'}</td>
                  <td className='space-x-2 p-2'><button className='text-sm underline' onClick={() => startEdit(t)}>Edit</button><button className='text-sm underline text-rose-700' onClick={() => setDeleteTarget(t)}>Delete</button></td>
                </>}
              </tr>)}</tbody>
            </table>
          </div>
          <div className='grid gap-2 rounded bg-slate-50 p-3 md:grid-cols-[1fr_auto_auto] md:items-end'>
            <label className='text-sm'><span className='mb-1 block font-medium'>Team name</span><input disabled={atLimit || saving} className='w-full rounded border p-2 disabled:cursor-not-allowed disabled:bg-slate-100' value={form.name} onChange={(e) => setNewTeams({ ...newTeams, [d.id]: { ...form, name: e.target.value } })} placeholder='Team Name' /></label>
            <label className='flex items-center gap-2 text-sm'><input disabled={saving} type='checkbox' checked={form.is_active} onChange={(e) => setNewTeams({ ...newTeams, [d.id]: { ...form, is_active: e.target.checked } })} /> Active</label>
            <button disabled={atLimit || saving} className='rounded bg-slate-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-400' onClick={() => addTeam(d.id, expectedCount, activeExisting.length)}>{atLimit ? 'Team Limit Reached' : 'Add Team'}</button>
          </div>
        </div>;
      })}
    </>}

    {deleteTarget && <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40'>
      <div className='w-full max-w-sm rounded bg-white p-4 shadow'>
        <p className='mb-3'>Delete team {deleteTarget.name}?</p>
        <div className='flex justify-end gap-2'>
          <button className='rounded border px-3 py-1' onClick={() => setDeleteTarget(null)}>Cancel</button>
          <button disabled={saving} className='rounded bg-rose-700 px-3 py-1 text-white disabled:bg-slate-400' onClick={confirmDelete}>Delete</button>
        </div>
      </div>
    </div>}
  </div>;
}
