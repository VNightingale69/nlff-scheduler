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
  surface_type?: string;
  notes?: string;
  field_area_name?: string;
  setup_constraints?: string;
  max_small_fields?: number;
  max_medium_fields?: number;
  max_large_fields?: number;
  max_total_fields?: number;
  can_support_small?: boolean;
  can_support_medium?: boolean;
  can_support_large?: boolean;
  is_active?: boolean;
  has_active_field_setup?: boolean;
  effective_is_active?: boolean;
  status_label?: string;
  status_warning?: string | null;
};

type Organization = {
  id: string;
  name: string;
};
const STADIUM_TYPE = 'STADIUM_SITE';
const SURFACE_TYPES = [
  { value: 'TURF_STADIUM', label: 'Turf Stadium' },
  { value: 'GRASS_FIELD', label: 'Grass Field' },
];
const HOST_CONFIG_OPTIONS = [
  { value: 'TWO_LARGE', label: '2 Large', used: 120, remaining: 0 },
  { value: 'ONE_MEDIUM_TWO_SMALL', label: '1 Medium + 2 Small', used: 120, remaining: 0 },
  { value: 'ONE_LARGE_ONE_MEDIUM', label: '1 Large + 1 Medium', used: 115, remaining: 5 },
  { value: 'TWO_MEDIUM', label: '2 Medium', used: 110, remaining: 10 },
  { value: 'THREE_SMALL', label: '3 Small', used: 100, remaining: 20 },
  { value: 'ONE_LARGE_ONE_SMALL', label: '1 Large + 1 Small', used: 90, remaining: 30 },
  { value: 'ONE_MEDIUM_ONE_SMALL', label: '1 Medium + 1 Small', used: 85, remaining: 35 },
];
const configLabel = (value: string) => HOST_CONFIG_OPTIONS.find((option) => option.value === value)?.label || value;

type DeleteCheck = {
  host_location_name: string;
  can_delete: boolean;
  reason?: string | null;
  recommended_action?: string | null;
  delete_message?: string | null;
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
  const [siteTypeByHostId, setSiteTypeByHostId] = useState<Record<string, string>>({});
  const [configsByHostId, setConfigsByHostId] = useState<Record<string, any[]>>({});
  const [zipCodeError, setZipCodeError] = useState('');

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
      const response: any = await apiFetch('/organizations?page_size=500', {}, getToken());
      setOrganizations(response.items || []);
    } catch {
      setOrganizations([]);
    }
  };

  const load = async () => {
    setLoading(true);
    try {
      const [hostResponse, areaResponse, configResponse]: any[] = await Promise.all([
        apiFetch('/host-locations?page_size=500', {}, getToken()),
        apiFetch('/physical-field-areas?page_size=1000', {}, getToken()),
        apiFetch('/host-location-configurations?page_size=1000', {}, getToken()),
      ]);
      const hosts = hostResponse.items || [];
      const areas = areaResponse.items || [];
      const configs = configResponse.items || [];
      const nextConfigsByHost: Record<string, any[]> = {};
      for (const config of configs) {
        if (!config?.host_location_id) continue;
        nextConfigsByHost[config.host_location_id] = [...(nextConfigsByHost[config.host_location_id] || []), config];
      }
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
      setConfigsByHostId(nextConfigsByHost);
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
    return missing;
  }, [form]);

  const getZipCodeError = () => {
    const zip = form.zip_code?.trim() || '';
    if (!zip) return 'Zip Code is required.';
    if (!/^\d{5}$/.test(zip)) return 'Zip Code must be 5 digits.';
    return '';
  };

  const save = async () => {
    const nextZipCodeError = getZipCodeError();
    if (nextZipCodeError) {
      setZipCodeError(nextZipCodeError);
      return;
    }

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
        address_line1: (form.address_line1 || form.address || '').trim(),
        address_line2: form.address_line2?.trim() || null,
        city: form.city?.trim(),
        state: form.state?.trim(),
        zip_code: form.zip_code?.trim(),
        surface_type: form.surface_type || 'GRASS_FIELD',
        notes: form.notes?.trim() || null,
        field_area_name: form.field_area_name?.trim() || null,
        setup_constraints: form.setup_constraints?.trim() || null,
        max_small_fields: Number(form.max_small_fields || 0),
        max_medium_fields: Number(form.max_medium_fields || 0),
        max_large_fields: Number(form.max_large_fields || 0),
        max_total_fields: Number(form.max_total_fields || 0),
        can_support_small: form.can_support_small !== false,
        can_support_medium: form.can_support_medium !== false,
        can_support_large: form.can_support_large !== false,
        ...(form.is_active !== undefined ? { is_active: Boolean(form.is_active) } : {}),
      };

      if (editingId) {
        await apiFetch(`/host-locations/${editingId}`, { method: 'PUT', body: JSON.stringify(payload) }, getToken());
      } else {
        await apiFetch('/host-locations', { method: 'POST', body: JSON.stringify(payload) }, getToken());
      }

      setMessage(editingId ? 'Updated successfully' : 'Created successfully');
      setType('ok');
      setForm({ is_active: true, state: 'WI', surface_type: 'GRASS_FIELD' });
      setEditingId(null);
      setZipCodeError('');
      load();
    } catch (e: any) {
      setMessage(e?.message || 'Save failed');
      setType('err');
    } finally {
      setSaving(false);
    }
  };

  const edit = (item: HostLocation) => {
    setForm({ ...item, address_line1: item.address_line1 || item.address || '', state: item.state || 'WI', surface_type: item.surface_type || 'GRASS_FIELD' });
    setEditingId(item.id);
    setZipCodeError('');
  };

  const openDeleteModal = async (item: HostLocation) => {
    setDeleteTarget(item);
    setDeleteCheck(null);
    setCheckingDelete(true);
    try {
      const summary: any = await apiFetch(`/host-locations/${item.id}/delete-check`, {}, getToken());
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
      const response = (await apiFetch(`/host-locations/${deleteTarget.id}`, { method: 'DELETE' }, getToken())) as DeleteResponse & DeleteCheck;
      if (response && response.can_delete === false) {
        setMessage('Cannot permanently delete because scheduled games reference this location. Mark inactive instead.');
        setType('err');
        return;
      }
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
        <FormField label='Surface Type' type='select' value={form.surface_type ?? 'GRASS_FIELD'} options={SURFACE_TYPES} onChange={(value) => setForm({ ...form, surface_type: String(value) })} />
        <FormField label='Notes' type='textarea' value={form.notes ?? ''} onChange={(value) => setForm({ ...form, notes: String(value) })} />
        {(form.surface_type ?? 'GRASS_FIELD') === 'GRASS_FIELD' ? (
          <div className='grid gap-3 rounded border bg-emerald-50/50 p-3 md:col-span-2 md:grid-cols-2'>
            <div className='md:col-span-2'>
              <h2 className='font-semibold'>Grass Field Physical Capacity</h2>
              <p className='text-sm text-slate-600'>Grass fields are fixed for the host date. Define the maximum number of Small, Medium, and Large fields this location can line before games start.</p>
            </div>
            <FormField label='Field Area Name' type='text' value={form.field_area_name ?? ''} onChange={(value) => setForm({ ...form, field_area_name: String(value) })} />
            <FormField label='Setup Constraints' type='textarea' value={form.setup_constraints ?? ''} onChange={(value) => setForm({ ...form, setup_constraints: String(value) })} />
            <FormField label='Maximum Small Fields' type='number' value={form.max_small_fields ?? 0} onChange={(value) => setForm({ ...form, max_small_fields: Number(value) })} />
            <FormField label='Maximum Medium Fields' type='number' value={form.max_medium_fields ?? 0} onChange={(value) => setForm({ ...form, max_medium_fields: Number(value) })} />
            <FormField label='Maximum Large Fields' type='number' value={form.max_large_fields ?? 0} onChange={(value) => setForm({ ...form, max_large_fields: Number(value) })} />
            <FormField label='Maximum Total Fields' type='number' value={form.max_total_fields ?? 0} onChange={(value) => setForm({ ...form, max_total_fields: Number(value) })} />
            <FormField label='Can Support Small' type='checkbox' value={form.can_support_small !== false} onChange={(value) => setForm({ ...form, can_support_small: Boolean(value) })} />
            <FormField label='Can Support Medium' type='checkbox' value={form.can_support_medium !== false} onChange={(value) => setForm({ ...form, can_support_medium: Boolean(value) })} />
            <FormField label='Can Support Large' type='checkbox' value={form.can_support_large !== false} onChange={(value) => setForm({ ...form, can_support_large: Boolean(value) })} />
          </div>
        ) : null}
        <div className='flex flex-col gap-1'>
          <FormField
            label='Zip Code'
            type='text'
            value={form.zip_code ?? ''}
            onChange={(value) => {
              setForm({ ...form, zip_code: String(value).replace(/\D/g, '').slice(0, 5) });
              if (zipCodeError) setZipCodeError('');
            }}
          />
          {zipCodeError && <p className='text-sm text-rose-700'>{zipCodeError}</p>}
        </div>
        <FormField label='Active' type='checkbox' value={form.is_active ?? true} onChange={(value) => setForm({ ...form, is_active: Boolean(value) })} />

        <div className='flex gap-2 md:col-span-2'>
          <button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-50' onClick={save} disabled={saving}>
            {saving ? 'Saving…' : editingId ? 'Update' : 'Create'}
          </button>
          {editingId && (
            <button className='rounded border px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50' onClick={() => { setForm({ is_active: true, state: 'WI', surface_type: 'GRASS_FIELD' }); setEditingId(null); setZipCodeError(''); }} disabled={saving}>
              Cancel
            </button>
          )}
        </div>
      </div>


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
                <th className='px-3 py-2'>Surface Type</th>
                <th className='px-3 py-2'>Supported Configurations</th>
                <th className='px-3 py-2'>Effective Status</th>
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
                  <td className='px-3 py-2'>{SURFACE_TYPES.find((surface) => surface.value === item.surface_type)?.label || item.surface_type || 'Other'}</td>
                  <td className='px-3 py-2'><div className='flex flex-col gap-1'>{item.surface_type === 'TURF_STADIUM' ? <>{(configsByHostId[item.id] || []).length ? (configsByHostId[item.id] || []).map((config: any) => <span key={config.id}>{configLabel(config.configuration_name)} — {config.space_used_yards ?? 0} used / {config.remaining_yards ?? 0} remaining ({(config.field_instances || []).join(', ')}){config.is_active ? '' : ' (Inactive)'}</span>) : <span className='text-slate-500'>No turf configuration selected</span>}<div className='mt-1 flex flex-wrap gap-1'>{HOST_CONFIG_OPTIONS.filter((option) => !(configsByHostId[item.id] || []).some((config: any) => config.configuration_name === option.value)).map((option) => <button key={option.value} type='button' className='rounded border px-2 py-0.5 text-xs text-emerald-700' title={`${option.used} yards used, ${option.remaining} yards remaining`} onClick={async () => { await apiFetch('/host-location-configurations', { method: 'POST', body: JSON.stringify({ host_location_id: item.id, configuration_name: option.value, is_active: true }) }, getToken()); load(); }}>+ {option.label}</button>)}</div></> : <span className='text-slate-600'>Grass forecast capacity: {item.max_small_fields ?? 0} Small / {item.max_medium_fields ?? 0} Medium / {item.max_large_fields ?? 0} Large • {item.max_total_fields ?? 0} total</span>}</div></td>
                  <td className='px-3 py-2'><div className='flex flex-col gap-1'><span>{item.status_label || ((item.effective_is_active ?? item.is_active) ? 'Active' : 'Inactive/Unavailable')}</span>{item.status_warning ? <span className='inline-flex w-fit rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800'>{item.status_warning}</span> : null}</div></td>
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
                <p className='font-medium'>{deleteCheck.can_delete ? 'Delete allowed. This will remove unused setup and generated slot records.' : `${deleteCheck.host_location_name} has related records:`}</p>
                {deleteCheck.can_delete && deleteCheck.delete_message && deleteCheck.delete_message !== 'Delete allowed. This will remove unused setup and generated slot records.' ? (
                  <p className='mt-2 font-semibold text-emerald-700'>{deleteCheck.delete_message}</p>
                ) : null}
                <ul className='mt-2 list-disc pl-6'>
                  {deleteCheck.dependencies.filter((d) => d.count > 0).map((d) => <li key={d.label}>{d.count} {d.label}</li>)}
                </ul>
                {!deleteCheck.can_delete && (
                  <>
                    <p className='mt-3 font-semibold text-rose-700'>Cannot permanently delete because scheduled games reference this location. Mark inactive instead.</p>
                  </>
                )}
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
