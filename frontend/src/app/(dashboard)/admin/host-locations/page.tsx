'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import Toast from '@/components/Toast';
import DataTable from '@/components/ui/DataTable';
import FormField from '@/components/ui/FormField';

type HostLocation = {
  id: string;
  organization_id: string;
  name: string;
  address: string;
  is_active?: boolean;
};

type Organization = {
  id: string;
  name: string;
};

type DeleteCheck = {
  host_location_name: string;
  can_delete: boolean;
  dependencies: Array<{ label: string; count: number }>;
};

export default function HostLocationsAdminPage() {
  const [items, setItems] = useState<HostLocation[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [query, setQuery] = useState('');
  const [form, setForm] = useState<Partial<HostLocation>>({ is_active: true });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [type, setType] = useState<'ok' | 'err'>('ok');
  const [deleteTarget, setDeleteTarget] = useState<HostLocation | null>(null);
  const [deleteCheck, setDeleteCheck] = useState<DeleteCheck | null>(null);
  const [checkingDelete, setCheckingDelete] = useState(false);

  const orgNameById = useMemo(() => Object.fromEntries(organizations.map((x) => [x.id, x.name])), [organizations]);

  const loadOrganizations = async () => {
    try {
      const response = await apiFetch('/organizations?page_size=500', {}, getToken());
      setOrganizations(response.items || []);
    } catch {
      setOrganizations([]);
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const d = await apiFetch(`/host-locations?search=${encodeURIComponent(query)}`, {}, getToken());
      setItems(d.items || []);
    } catch {
      setMessage('Failed to load host locations');
      setType('err');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    loadOrganizations();
  }, []);

  const missingRequired = useMemo(() => {
    const missing: string[] = [];
    if (!form.organization_id) missing.push('Organization');
    if (!form.name?.trim()) missing.push('Name');
    if (!form.address?.trim()) missing.push('Address');
    return missing;
  }, [form]);

  const save = async () => {
    if (missingRequired.length) {
      setMessage(`Missing: ${missingRequired.join(', ')}`);
      setType('err');
      return;
    }

    setSaving(true);
    try {
      const payload = {
        organization_id: form.organization_id,
        name: form.name?.trim(),
        address: form.address?.trim(),
        ...(form.is_active !== undefined ? { is_active: Boolean(form.is_active) } : {}),
      };

      if (editingId) {
        await apiFetch(`/host-locations/${editingId}`, { method: 'PUT', body: JSON.stringify(payload) }, getToken());
      } else {
        await apiFetch('/host-locations', { method: 'POST', body: JSON.stringify(payload) }, getToken());
      }

      setMessage(editingId ? 'Updated successfully' : 'Created successfully');
      setType('ok');
      setForm({ is_active: true });
      setEditingId(null);
      load();
    } catch (e: any) {
      setMessage(e?.message || 'Save failed');
      setType('err');
    } finally {
      setSaving(false);
    }
  };

  const edit = (item: HostLocation) => {
    setForm(item);
    setEditingId(item.id);
  };

  const openDeleteModal = async (item: HostLocation) => {
    setDeleteTarget(item);
    setDeleteCheck(null);
    setCheckingDelete(true);
    try {
      const summary = await apiFetch(`/host-locations/${item.id}/delete-check`, {}, getToken());
      setDeleteCheck(summary);
    } catch (e: any) {
      setMessage(e?.message || 'Failed to load dependency summary');
      setType('err');
    } finally {
      setCheckingDelete(false);
    }
  };

  const closeDeleteModal = () => {
    setDeleteTarget(null);
    setDeleteCheck(null);
    setCheckingDelete(false);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await apiFetch(`/host-locations/${deleteTarget.id}`, { method: 'DELETE' }, getToken());
      setMessage('Deleted successfully');
      setType('ok');
      closeDeleteModal();
      load();
    } catch (e: any) {
      setMessage(e?.message || 'Delete failed');
      setType('err');
    }
  };

  const deactivateHost = async () => {
    if (!deleteTarget) return;
    try {
      await apiFetch(
        `/host-locations/${deleteTarget.id}`,
        { method: 'PUT', body: JSON.stringify({ ...deleteTarget, is_active: false }) },
        getToken(),
      );
      setMessage(`${deleteTarget.name} marked inactive`);
      setType('ok');
      closeDeleteModal();
      load();
    } catch (e: any) {
      setMessage(e?.message || 'Failed to mark host location inactive');
      setType('err');
    }
  };

  return (
    <div className='space-y-4'>
      <Toast message={message} type={type} />
      <h1 className='text-2xl font-bold'>Host Locations</h1>

      <div className='flex gap-2'>
        <input className='w-full max-w-sm rounded border p-2' value={query} onChange={(e) => setQuery(e.target.value)} placeholder='Search...' />
        <button className='rounded bg-slate-700 px-3 py-2 text-white' onClick={load}>Filter</button>
      </div>

      <div className='grid gap-3 rounded border p-4 md:grid-cols-2'>
        <label className='flex flex-col gap-1'>
          <span className='text-sm font-medium'>Organization</span>
          <select className='rounded border p-2' value={form.organization_id ?? ''} onChange={(e) => setForm({ ...form, organization_id: e.target.value })}>
            <option value=''>Select organization</option>
            {organizations.map((org) => (
              <option key={org.id} value={org.id}>{org.name}</option>
            ))}
          </select>
        </label>

        <FormField label='Name' type='text' value={form.name ?? ''} onChange={(value) => setForm({ ...form, name: String(value) })} />
        <FormField label='Address' type='text' value={form.address ?? ''} onChange={(value) => setForm({ ...form, address: String(value) })} />
        <FormField label='Active' type='checkbox' value={form.is_active ?? true} onChange={(value) => setForm({ ...form, is_active: Boolean(value) })} />

        <div className='flex gap-2 md:col-span-2'>
          <button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-50' onClick={save} disabled={saving}>
            {saving ? 'Saving…' : editingId ? 'Update' : 'Create'}
          </button>
          {editingId && (
            <button className='rounded border px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50' onClick={() => { setForm({ is_active: true }); setEditingId(null); }} disabled={saving}>
              Cancel
            </button>
          )}
        </div>
      </div>

      {loading ? <p>Loading records...</p> : items.length === 0 ? <div className='rounded border border-dashed p-6 text-center text-slate-500'>No records yet.</div> : (
        <DataTable
          items={items}
          columns={['organization_id', 'name', 'address', 'is_active']}
          valueLabels={{ organization_id: orgNameById }}
          onEdit={edit}
          onDelete={openDeleteModal}
        />
      )}

      {deleteTarget && (
        <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'>
          <div className='w-full max-w-lg rounded bg-white p-5 shadow-lg'>
            <h2 className='text-lg font-semibold'>Delete Host Location</h2>
            <p className='mt-2 text-sm text-slate-700'>You are deleting <span className='font-semibold'>{deleteTarget.name}</span>. This may impact fields, availability, and future schedules.</p>
            {checkingDelete && <p className='mt-3 text-sm text-slate-500'>Checking dependencies...</p>}
            {!checkingDelete && deleteCheck && (
              <div className='mt-3 rounded border p-3 text-sm'>
                <p className='font-medium'>{deleteCheck.can_delete ? 'No blocking dependencies found.' : `${deleteCheck.host_location_name} cannot be deleted because:`}</p>
                <ul className='mt-2 list-disc pl-6'>
                  {deleteCheck.dependencies.filter((d) => d.count > 0).map((d) => <li key={d.label}>{d.count} {d.label}</li>)}
                </ul>
              </div>
            )}
            <div className='mt-4 flex flex-wrap justify-end gap-2'>
              <button className='rounded border px-3 py-2' onClick={closeDeleteModal}>Cancel</button>
              <button className='rounded border border-amber-500 px-3 py-2 text-amber-700' onClick={deactivateHost}>Mark Inactive</button>
              <button className='rounded bg-rose-700 px-3 py-2 text-white disabled:opacity-50' disabled={!!deleteCheck && !deleteCheck.can_delete} onClick={confirmDelete}>Confirm Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
