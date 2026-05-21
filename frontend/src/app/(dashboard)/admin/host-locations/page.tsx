'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import Toast from '@/components/Toast';
import FormField from '@/components/ui/FormField';
import Link from 'next/link';

type HostLocation = {
  id: string;
  organization_id: string;
  name: string;
  address?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  is_active?: boolean;
};

type Organization = {
  id: string;
  name: string;
};
const STADIUM_TYPE = 'STADIUM_SITE';

type DeleteCheck = {
  host_location_name: string;
  can_delete: boolean;
  dependencies: Array<{ label: string; count: number }>;
};

type DeleteResponse = {
  ok: boolean;
  deleted?: Record<string, number>;
};

export default function HostLocationsAdminPage() {
  const [items, setItems] = useState<HostLocation[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [query, setQuery] = useState('');
  const [form, setForm] = useState<Partial<HostLocation>>({ is_active: true, state: 'WI' });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [type, setType] = useState<'ok' | 'err'>('ok');
  const [deleteTarget, setDeleteTarget] = useState<HostLocation | null>(null);
  const [deleteCheck, setDeleteCheck] = useState<DeleteCheck | null>(null);
  const [checkingDelete, setCheckingDelete] = useState(false);
  const [cascadeConfirmed, setCascadeConfirmed] = useState(false);
  const [siteTypeByHostId, setSiteTypeByHostId] = useState<Record<string, string>>({});

  const orgNameById = useMemo(() => Object.fromEntries(organizations.map((x) => [x.id, x.name])), [organizations]);
  const displayItems = useMemo(
    () => items.map((item) => {
      const city = item.city?.trim() || '';
      const state = item.state?.trim() || '';
      return {
        ...item,
        address_line1: item.address_line1 || item.address || '',
        location: city && state ? `${city}, ${state}` : city || state || '-',
        site_type: siteTypeByHostId[item.id] || '—',
      };
    }),
    [items, siteTypeByHostId],
  );

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
      const [hostResponse, areaResponse] = await Promise.all([
        apiFetch('/host-locations?page_size=500', {}, getToken()),
        apiFetch('/physical-field-areas?page_size=1000', {}, getToken()),
      ]);
      const hosts = hostResponse.items || [];
      const areas = areaResponse.items || [];
      const nextSiteTypes: Record<string, string> = {};
      for (const area of areas) {
        if (!area?.host_location_id || nextSiteTypes[area.host_location_id]) continue;
        nextSiteTypes[area.host_location_id] = area.field_space_type === STADIUM_TYPE ? 'Stadium Site' : 'Grass/Park Site';
      }
      const normalizedQuery = query.trim().toLowerCase();
      const filteredHosts = normalizedQuery
        ? hosts.filter((item: HostLocation) => {
            const siteType = nextSiteTypes[item.id] || '';
            const haystack = [
              orgNameById[item.organization_id] || '',
              item.name || '',
              item.address_line1 || item.address || '',
              item.city || '',
              item.state || '',
              item.zip_code || '',
              siteType,
            ]
              .join(' ')
              .toLowerCase();
            return haystack.includes(normalizedQuery);
          })
        : hosts;
      setSiteTypeByHostId(nextSiteTypes);
      setItems(filteredHosts);
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
    if (!form.name?.trim()) missing.push('Hosting Site Name');
    if (!form.address_line1?.trim() && !form.address?.trim()) missing.push('Street Address');
    if (!form.city?.trim()) missing.push('City');
    if (!form.state?.trim()) missing.push('State');
    if (!form.zip_code?.trim()) missing.push('Zip Code');
    return missing;
  }, [form]);
  const zipCodeError = useMemo(() => {
    const zip = form.zip_code?.trim() || '';
    if (!zip) return 'Zip Code is required.';
    if (!/^\d{5}$/.test(zip)) return 'Zip Code must be 5 digits.';
    return '';
  }, [form.zip_code]);

  const save = async () => {
    if (missingRequired.length || zipCodeError) {
      if (zipCodeError) {
        setMessage(zipCodeError);
      } else {
        setMessage(`Missing: ${missingRequired.join(', ')}`);
      }
      setType('err');
      return;
    }

    setSaving(true);
    try {
      const payload = {
        organization_id: form.organization_id,
        name: form.name?.trim(),
        address: form.address?.trim(),
        address_line1: (form.address_line1 || form.address || '').trim(),
        address_line2: form.address_line2?.trim() || null,
        city: form.city?.trim(),
        state: form.state?.trim(),
        zip_code: form.zip_code?.trim(),
        ...(form.is_active !== undefined ? { is_active: Boolean(form.is_active) } : {}),
      };

      if (editingId) {
        await apiFetch(`/host-locations/${editingId}`, { method: 'PUT', body: JSON.stringify(payload) }, getToken());
      } else {
        await apiFetch('/host-locations', { method: 'POST', body: JSON.stringify(payload) }, getToken());
      }

      setMessage(editingId ? 'Updated successfully' : 'Created successfully');
      setType('ok');
      setForm({ is_active: true, state: 'WI' });
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
    setForm({ ...item, address_line1: item.address_line1 || item.address || '', state: item.state || 'WI' });
    setEditingId(item.id);
  };

  const openDeleteModal = async (item: HostLocation) => {
    setDeleteTarget(item);
    setDeleteCheck(null);
    setCheckingDelete(true);
    setCascadeConfirmed(false);
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
      const hasDependencies = !!deleteCheck && !deleteCheck.can_delete;
      const endpoint = hasDependencies ? `/host-locations/${deleteTarget.id}?force=true` : `/host-locations/${deleteTarget.id}`;
      const response = (await apiFetch(endpoint, { method: 'DELETE' }, getToken())) as DeleteResponse;
      if (response?.deleted) {
        const summary = Object.entries(response.deleted)
          .filter(([, count]) => count > 0)
          .map(([key, count]) => `${count} ${key.replaceAll('_', ' ')}`)
          .join(', ');
        setMessage(summary ? `Deleted successfully: ${summary}` : 'Deleted successfully');
      } else {
        setMessage('Deleted successfully');
      }
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

        <FormField label='Hosting Site Name' type='text' value={form.name ?? ''} onChange={(value) => setForm({ ...form, name: String(value) })} />
        <FormField label='Street Address' type='text' value={form.address_line1 ?? form.address ?? ''} onChange={(value) => setForm({ ...form, address_line1: String(value) })} />
        <FormField label='Address Line 2 (Optional)' type='text' value={form.address_line2 ?? ''} onChange={(value) => setForm({ ...form, address_line2: String(value) })} />
        <FormField label='City' type='text' value={form.city ?? ''} onChange={(value) => setForm({ ...form, city: String(value) })} />
        <FormField label='State' type='text' value={form.state ?? 'WI'} onChange={(value) => setForm({ ...form, state: String(value) })} />
        <FormField label='Zip Code' type='text' value={form.zip_code ?? ''} onChange={(value) => setForm({ ...form, zip_code: String(value).replace(/\D/g, '').slice(0, 5) })} />
        <FormField label='Active' type='checkbox' value={form.is_active ?? true} onChange={(value) => setForm({ ...form, is_active: Boolean(value) })} />

        <div className='flex gap-2 md:col-span-2'>
          <button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-50' onClick={save} disabled={saving}>
            {saving ? 'Saving…' : editingId ? 'Update' : 'Create'}
          </button>
          {editingId && (
            <button className='rounded border px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50' onClick={() => { setForm({ is_active: true, state: 'WI' }); setEditingId(null); }} disabled={saving}>
              Cancel
            </button>
          )}
        </div>
      </div>

      {zipCodeError && <p className='text-sm text-rose-700'>{zipCodeError}</p>}

      {loading ? <p>Loading records...</p> : items.length === 0 ? <div className='rounded border border-dashed p-6 text-center text-slate-500'>No records yet.</div> : (
        <div className='overflow-x-auto rounded border'>
          <table className='w-full text-left text-sm'>
            <thead className='bg-slate-100'>
              <tr>
                <th className='px-3 py-2'>Organization</th>
                <th className='px-3 py-2'>Hosting Site Name</th>
                <th className='px-3 py-2'>Street Address</th>
                <th className='px-3 py-2'>Location</th>
                <th className='px-3 py-2'>Zip Code</th>
                <th className='px-3 py-2'>Site Type</th>
                <th className='px-3 py-2'>Active</th>
                <th className='px-3 py-2'>Actions</th>
              </tr>
            </thead>
            <tbody>
              {displayItems.map((item) => (
                <tr key={item.id} className='border-t'>
                  <td className='px-3 py-2'>{orgNameById[item.organization_id] || '-'}</td>
                  <td className='px-3 py-2'>{item.name}</td>
                  <td className='px-3 py-2'>{item.address_line1 || '-'}</td>
                  <td className='px-3 py-2'>{(item as any).location}</td>
                  <td className='px-3 py-2'>{item.zip_code || '-'}</td>
                  <td className='px-3 py-2'>{(item as any).site_type}</td>
                  <td className='px-3 py-2'>{item.is_active ? 'Active' : 'Inactive'}</td>
                  <td className='space-x-2 px-3 py-2'>
                    <button className='text-blue-700' onClick={() => edit(item)}>Edit</button>
                    <button className='text-rose-700' onClick={() => openDeleteModal(item)}>Delete</button>
                    <Link className='text-emerald-700' href={`/admin/hosting-availability?host_location_id=${encodeURIComponent(item.id)}&organization_id=${encodeURIComponent(item.organization_id)}`}>View Availability</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteTarget && (
        <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'>
          <div className='w-full max-w-lg rounded bg-white p-5 shadow-lg'>
            <h2 className='text-lg font-semibold'>Delete Host Location</h2>
            <p className='mt-2 text-sm text-slate-700'>You are deleting <span className='font-semibold'>{deleteTarget.name}</span>. This may impact fields, availability, and future schedules.</p>
            {checkingDelete && <p className='mt-3 text-sm text-slate-500'>Checking dependencies...</p>}
            {!checkingDelete && deleteCheck && (
              <div className='mt-3 rounded border p-3 text-sm'>
                <p className='font-medium'>{deleteCheck.can_delete ? 'No blocking dependencies found.' : `${deleteCheck.host_location_name} has related records:`}</p>
                <ul className='mt-2 list-disc pl-6'>
                  {deleteCheck.dependencies.filter((d) => d.count > 0).map((d) => <li key={d.label}>{d.count} {d.label}</li>)}
                </ul>
                {!deleteCheck.can_delete && (
                  <>
                    <p className='mt-3 font-semibold text-rose-700'>This will permanently delete this Host Location and all related records. This action cannot be undone.</p>
                    <label className='mt-3 flex items-start gap-2'>
                      <input
                        type='checkbox'
                        className='mt-1'
                        checked={cascadeConfirmed}
                        onChange={(e) => setCascadeConfirmed(e.target.checked)}
                      />
                      <span>I understand this will permanently delete the host location and all related records.</span>
                    </label>
                  </>
                )}
              </div>
            )}
            <div className='mt-4 flex flex-wrap justify-end gap-2'>
              <button className='rounded border px-3 py-2' onClick={closeDeleteModal}>Cancel</button>
              <button className='rounded border border-amber-500 px-3 py-2 text-amber-700' onClick={deactivateHost}>Mark Inactive</button>
              <button className='rounded bg-rose-700 px-3 py-2 text-white disabled:opacity-50' disabled={!!deleteCheck && !deleteCheck.can_delete && !cascadeConfirmed} onClick={confirmDelete}>Confirm Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
