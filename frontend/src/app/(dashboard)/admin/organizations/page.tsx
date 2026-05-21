'use client';

import { useEffect, useMemo, useState } from 'react';
import { ApiError, apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';
import Toast from '@/components/Toast';
import FormField from '@/components/ui/FormField';

type Organization = { id: string; name: string; is_active: boolean };
type DeleteDependencyErrorDetail = { error?: string; message?: string; dependencies?: Record<string, number | string> };

export default function OrganizationsAdminPage() {
  const [items, setItems] = useState<Organization[]>([]);
  const [query, setQuery] = useState('');
  const [form, setForm] = useState<Partial<Organization>>({ is_active: true });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [type, setType] = useState<'ok' | 'err'>('ok');
  const [deleteTarget, setDeleteTarget] = useState<Organization | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [cascadeConfirmed, setCascadeConfirmed] = useState(false);

  const user = getAuthUser();
  const isLeagueAdmin = user?.role_name === 'league_admin';

  const load = async () => {
    setLoading(true);
    try {
      const d = await apiFetch(`/organizations?page_size=500&search=${encodeURIComponent(query)}`, {}, getToken());
      setItems(d.items || []);
    } catch (e: any) {
      setMessage(e?.message || 'Failed to load organizations');
      setType('err');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const missingRequired = useMemo(() => (!form.name?.trim() ? ['Name'] : []), [form]);

  const save = async () => {
    if (missingRequired.length) { setMessage(`Missing: ${missingRequired.join(', ')}`); setType('err'); return; }
    setSaving(true);
    try {
      const payload = { name: form.name?.trim(), is_active: Boolean(form.is_active) };
      if (editingId) await apiFetch(`/organizations/${editingId}`, { method: 'PUT', body: JSON.stringify(payload) }, getToken());
      else await apiFetch('/organizations', { method: 'POST', body: JSON.stringify(payload) }, getToken());
      setMessage(editingId ? 'Updated successfully' : 'Created successfully'); setType('ok'); setForm({ is_active: true }); setEditingId(null); load();
    } catch (e: any) { setMessage(e?.message || 'Save failed'); setType('err'); }
    finally { setSaving(false); }
  };

  const openDeleteModal = (item: Organization) => {
    setDeleteTarget(item); setCascadeConfirmed(false); setDeleteError('');
  };

  const closeDeleteModal = () => { setDeleteTarget(null); setDeleteError(''); setCascadeConfirmed(false); };

  const deactivateOrganization = async () => {
    if (!deleteTarget) return;
    setDeleteError('');
    try {
      await apiFetch(`/organizations/${deleteTarget.id}`, { method: 'PUT', body: JSON.stringify({ ...deleteTarget, is_active: false }) }, getToken());
      setMessage(`${deleteTarget.name} marked inactive`); setType('ok'); closeDeleteModal(); load();
    } catch {
      setDeleteError('Unable to mark organization inactive.');
      setMessage('Unable to mark organization inactive.');
      setType('err');
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleteError('');
    try {
      const endpoint = isLeagueAdmin ? `/organizations/${deleteTarget.id}?force=true` : `/organizations/${deleteTarget.id}`;
      await apiFetch(endpoint, { method: 'DELETE' }, getToken());
      setMessage('Deleted successfully'); setType('ok'); closeDeleteModal(); load();
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : undefined;
      const detailObject = (apiError?.detail && typeof apiError.detail === 'object' ? apiError.detail : apiError?.details) as DeleteDependencyErrorDetail | undefined;
      const fallback = 'Unable to delete organization. Check backend logs.';
      const serverMessage = detailObject?.message ? `${fallback}` : fallback;
      setDeleteError(serverMessage);
      setMessage(serverMessage);
      setType('err');
    }
  };


  const requiresCascadeConfirmation = isLeagueAdmin;
  const deleteButtonDisabled = requiresCascadeConfirmation && !cascadeConfirmed;

  return <div className='space-y-4'>
    <Toast message={message} type={type} />
    <h1 className='text-2xl font-bold'>Organizations</h1>
    <div className='flex gap-2'><input className='w-full max-w-sm rounded border p-2' value={query} onChange={(e) => setQuery(e.target.value)} placeholder='Search...' /><button className='rounded bg-slate-700 px-3 py-2 text-white' onClick={load}>Filter</button></div>
    <div className='grid gap-3 rounded border p-4 md:grid-cols-2'>
      <FormField label='Name' type='text' value={form.name ?? ''} onChange={(v) => setForm({ ...form, name: String(v) })} />
      <FormField label='Active' type='checkbox' value={form.is_active ?? true} onChange={(v) => setForm({ ...form, is_active: Boolean(v) })} />
      <div className='md:col-span-2 flex gap-2'><button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:opacity-50' onClick={save} disabled={saving}>{saving ? 'Saving…' : editingId ? 'Update' : 'Create'}</button>{editingId && <button className='rounded border px-4 py-2' onClick={() => { setForm({ is_active: true }); setEditingId(null); }}>Cancel</button>}</div>
    </div>

    {loading ? <p>Loading records...</p> : <div className='overflow-x-auto rounded border'><table className='w-full text-left text-sm'><thead className='bg-slate-100'><tr><th className='px-3 py-2'>Name</th><th className='px-3 py-2'>Active</th><th className='px-3 py-2'>Actions</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} className='border-t'><td className='px-3 py-2'>{item.name}</td><td className='px-3 py-2'>{item.is_active ? 'Active' : 'Inactive'}</td><td className='space-x-2 px-3 py-2'><button className='text-blue-700' onClick={() => { setForm(item); setEditingId(item.id); }}>Edit</button><button className='text-rose-700' onClick={() => openDeleteModal(item)}>Delete</button></td></tr>)}</tbody></table></div>}

    {deleteTarget && <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'><div className='w-full max-w-lg rounded bg-white p-5 shadow-lg'>
      <h2 className='text-lg font-semibold'>Organization Actions</h2>
      <p className='mt-2 text-sm text-slate-700'>You are deleting <span className='font-semibold'>{deleteTarget.name}</span>.</p>
      {deleteError && <p className='mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700'>{deleteError}</p>}
      <p className='mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800'>This will permanently delete the organization and all related setup data, including host locations, hosting site setup, availability, division participation, and teams. This action cannot be undone.</p>
      {requiresCascadeConfirmation && <div className='mt-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm'><label className='flex items-start gap-2'><input type='checkbox' className='mt-1' checked={cascadeConfirmed} onChange={(e) => setCascadeConfirmed(e.target.checked)} /><span>I understand this will permanently delete this organization and all related setup data.</span></label><p className='mt-2 text-rose-700'>This action cannot be undone.</p></div>}
      <div className='mt-4 flex flex-wrap justify-end gap-2'><button className='rounded border px-3 py-2' onClick={closeDeleteModal}>Cancel</button><button className='rounded border border-amber-500 px-3 py-2 text-amber-700' onClick={deactivateOrganization}>Mark Inactive</button><button className={`rounded px-3 py-2 text-white ${deleteButtonDisabled ? 'bg-slate-400' : 'bg-rose-700 hover:bg-rose-800'}`} disabled={deleteButtonDisabled} onClick={confirmDelete}>Delete Organization</button></div>
    </div></div>}
  </div>;
}
