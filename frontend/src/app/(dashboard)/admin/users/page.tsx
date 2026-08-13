'use client';

import { FormEvent, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';

type User = { id: string; email: string; full_name: string; role_name: string; organization_id?: string | null; is_active: boolean; deleted_at?: string | null };
type Organization = { id: string; name: string };

const emptyForm = { email: '', full_name: '', password: '', role_name: 'COMMUNITY_ADMIN', organization_id: '', is_active: true };

export default function UsersPage() {
  const { accessToken } = useAuthSession();
  const [items, setItems] = useState<User[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editing, setEditing] = useState<User | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [temporaryPassword, setTemporaryPassword] = useState('');
  const [filters, setFilters] = useState({ search: '', role: '', organization_id: '', is_active: '' });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const params = new URLSearchParams({ page_size: '500' });
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
    try {
      const [users, orgs] = await Promise.all([
        apiFetch(`/users?${params}`, {}, accessToken),
        apiFetch('/organizations?page_size=500', {}, accessToken),
      ]);
      setItems(users.items || []); setOrganizations(orgs.items || []); setError('');
    } catch (e: any) { setError(e?.message || 'Unable to load users.'); }
  };
  useEffect(() => { if (accessToken) load(); }, [accessToken]);

  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    const payload = { ...form, organization_id: form.organization_id || null };
    try {
      if (editing) {
        const { password, ...update } = payload;
        await apiFetch(`/users/${editing.id}`, { method: 'PUT', body: JSON.stringify(update) }, accessToken);
      } else await apiFetch('/users', { method: 'POST', body: JSON.stringify(payload) }, accessToken);
      setMessage(editing ? 'User updated successfully.' : 'User created successfully.'); setEditing(null); setForm(emptyForm); await load();
    } catch (e: any) { setError(e?.message || 'Unable to save user.'); } finally { setBusy(false); }
  };
  const edit = (user: User) => { setEditing(user); setForm({ email: user.email, full_name: user.full_name, password: '', role_name: user.role_name, organization_id: user.organization_id || '', is_active: user.is_active }); };
  const setActive = async (user: User, is_active: boolean) => {
    try { await apiFetch(`/users/${user.id}`, { method: 'PUT', body: JSON.stringify({ ...user, is_active }) }, accessToken); setMessage(`User ${is_active ? 'activated' : 'deactivated'} successfully.`); await load(); }
    catch (e: any) { setError(e?.message || 'Unable to update user.'); }
  };
  const remove = async () => {
    if (!deleteTarget) return; setBusy(true); setError('');
    try { await apiFetch(`/users/${deleteTarget.id}`, { method: 'DELETE' }, accessToken); setDeleteTarget(null); setMessage('User deleted successfully.'); await load(); }
    catch (e: any) { setError(e?.message || 'Unable to delete user.'); } finally { setBusy(false); }
  };
  const resetPassword = async () => {
    if (!resetTarget) return;
    try { await apiFetch(`/users/${resetTarget.id}/reset-password`, { method: 'POST', body: JSON.stringify({ password: temporaryPassword }) }, accessToken); setResetTarget(null); setTemporaryPassword(''); setMessage('Temporary password reset successfully.'); }
    catch (e: any) { setError(e?.message || 'Unable to reset temporary password.'); }
  };
  const orgName = (id?: string | null) => organizations.find((org) => org.id === id)?.name || '—';
  const deleteTitle = deleteTarget?.role_name === 'COMMUNITY_ADMIN' ? 'Delete Community Administrator?' : 'Delete User?';

  return <div className='space-y-4'>
    <div><h1 className='text-2xl font-bold'>Users</h1><p className='text-sm text-slate-600'>Manage administrator accounts without changing their associated community data.</p></div>
    {message && <div className='rounded border border-green-200 bg-green-50 p-3 text-sm text-green-800'>{message}</div>}
    {error && <div className='rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800'>{error}</div>}
    <form onSubmit={save} className='grid gap-3 rounded border bg-white p-4 md:grid-cols-3'>
      <input required className='rounded border p-2' placeholder='Display name' value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
      <input required type='email' className='rounded border p-2' placeholder='Email' value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      {!editing && <input required type='password' className='rounded border p-2' placeholder='Temporary password' value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />}
      <select className='rounded border p-2' value={form.role_name} onChange={(e) => setForm({ ...form, role_name: e.target.value })}><option value='COMMUNITY_ADMIN'>Community Administrator</option><option value='SCHEDULING_ADMIN'>Scheduling Administrator</option><option value='LEAGUE_ADMIN'>League Administrator</option></select>
      <select className='rounded border p-2' value={form.organization_id} onChange={(e) => setForm({ ...form, organization_id: e.target.value })}><option value=''>No community</option>{organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}</select>
      <label className='flex items-center gap-2'><input type='checkbox' checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active</label>
      <div><button disabled={busy} className='rounded bg-blue-700 px-3 py-2 text-white'>{editing ? 'Save Changes' : 'Create User'}</button>{editing && <button type='button' className='ml-2 px-3 py-2' onClick={() => { setEditing(null); setForm(emptyForm); }}>Cancel</button>}</div>
    </form>
    <form className='grid gap-2 rounded border bg-white p-3 md:grid-cols-5' onSubmit={(e) => { e.preventDefault(); load(); }}><input className='rounded border p-2' placeholder='Search users' value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} /><select className='rounded border p-2' value={filters.role} onChange={(e) => setFilters({ ...filters, role: e.target.value })}><option value=''>All roles</option><option value='COMMUNITY_ADMIN'>Community Admin</option><option value='SCHEDULING_ADMIN'>Scheduling Admin</option><option value='LEAGUE_ADMIN'>League Admin</option></select><select className='rounded border p-2' value={filters.organization_id} onChange={(e) => setFilters({ ...filters, organization_id: e.target.value })}><option value=''>All communities</option>{organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}</select><select className='rounded border p-2' value={filters.is_active} onChange={(e) => setFilters({ ...filters, is_active: e.target.value })}><option value=''>All statuses</option><option value='true'>Active</option><option value='false'>Inactive</option></select><button className='rounded bg-slate-800 p-2 text-white'>Apply Filters</button></form>
    <div className='overflow-x-auto rounded border bg-white'><table className='min-w-full text-sm'><thead className='bg-slate-100 text-left'><tr>{['Name', 'Email', 'Role', 'Community', 'Status', 'Actions'].map((x) => <th className='p-2' key={x}>{x}</th>)}</tr></thead><tbody>{items.map((user) => <tr key={user.id} className='border-t'><td className='p-2'>{user.full_name}</td><td className='p-2'>{user.email}</td><td className='p-2'>{user.role_name}</td><td className='p-2'>{orgName(user.organization_id)}</td><td className='p-2'>{user.is_active ? 'Active' : 'Inactive'}</td><td className='space-x-2 p-2'><button onClick={() => edit(user)} className='underline'>Edit</button><button onClick={() => setActive(user, !user.is_active)} className='underline'>{user.is_active ? 'Deactivate' : 'Activate'}</button><button onClick={() => setResetTarget(user)} className='underline'>Reset Temporary Password</button><button onClick={() => setDeleteTarget(user)} className='text-red-700 underline'>Delete</button></td></tr>)}</tbody></table></div>
    {deleteTarget && <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'><div className='max-w-lg rounded bg-white p-5 shadow-xl'><h2 className='text-lg font-bold'>{deleteTitle}</h2><p className='mt-3'>This will remove access for <strong>{deleteTarget.full_name}</strong>.</p><p className='mt-3 text-sm text-slate-700'>The associated community, teams, facilities, schedules, and league data will not be deleted.</p><div className='mt-5 flex justify-end gap-2'><button onClick={() => setDeleteTarget(null)} className='rounded border px-3 py-2'>Cancel</button><button disabled={busy} onClick={remove} className='rounded bg-red-700 px-3 py-2 text-white'>Delete User</button></div></div></div>}
    {resetTarget && <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'><div className='rounded bg-white p-5'><h2 className='font-bold'>Reset Temporary Password</h2><input type='password' className='mt-3 w-full rounded border p-2' value={temporaryPassword} onChange={(e) => setTemporaryPassword(e.target.value)} /><div className='mt-3 flex gap-2'><button onClick={() => setResetTarget(null)}>Cancel</button><button className='rounded bg-blue-700 px-3 py-2 text-white' onClick={resetPassword}>Reset Password</button></div></div></div>}
  </div>;
}
