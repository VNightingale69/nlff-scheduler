'use client';
import { useEffect, useMemo, useState } from 'react';
import Toast from './Toast';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

const TURF_STADIUM = 'TURF_STADIUM';
const GRASS_FIELD = 'GRASS_FIELD';
const FIELD_TYPES = ['SMALL', 'MEDIUM', 'LARGE'];

const DIVISION_COMPATIBILITY = {
  SMALL: ['Coed K-1', 'Coed 2-3', 'Girls K-2'],
  MEDIUM: ['Coed 4-5', 'Girls 3-5'],
  LARGE: ['Coed 6-7', 'Coed 8', 'Girls 6-8'],
};

const TURF_LAYOUTS = [
  { name: 'TWO_LARGE', title: 'Two Large Fields', spaceUsed: 120, remaining: 0, large: 2, medium: 0, small: 0 },
  { name: 'ONE_MEDIUM_TWO_SMALL', title: 'One Medium Field + Two Small Fields', spaceUsed: 120, remaining: 0, large: 0, medium: 1, small: 2 },
  { name: 'ONE_LARGE_ONE_MEDIUM', title: 'One Large Field + One Medium Field', spaceUsed: 115, remaining: 5, large: 1, medium: 1, small: 0 },
  { name: 'TWO_MEDIUM', title: 'Two Medium Fields', spaceUsed: 110, remaining: 10, large: 0, medium: 2, small: 0 },
  { name: 'THREE_SMALL', title: 'Three Small Fields', spaceUsed: 100, remaining: 20, large: 0, medium: 0, small: 3 },
  { name: 'ONE_LARGE_ONE_SMALL', title: 'One Large Field + One Small Field', spaceUsed: 90, remaining: 30, large: 1, medium: 0, small: 1 },
  { name: 'ONE_MEDIUM_ONE_SMALL', title: 'One Medium Field + One Small Field', spaceUsed: 85, remaining: 35, large: 0, medium: 1, small: 1 },
];

const formatSurfaceType = (value?: string) => value === TURF_STADIUM ? 'Turf Stadium' : value === GRASS_FIELD ? 'Grass Field' : 'Not set';
const fieldTypeLabel = (value?: string) => value ? value.charAt(0).toUpperCase() + value.slice(1).toLowerCase() : '—';
const configuredFieldsText = (count: number) => `${count} active configured field${count === 1 ? '' : 's'}`;

const supportedGroups = (layout: typeof TURF_LAYOUTS[number]) => {
  const groups: string[] = [];
  if (layout.small) groups.push('Coed K-1', 'Coed 2-3', 'Girls K-2');
  if (layout.medium) groups.push('Coed 4-5', 'Girls 3-5');
  if (layout.large) groups.push('Coed 6-7', 'Coed 8', 'Girls 6-8');
  return groups.join(', ');
};

export default function FieldAreaManager() {
  const token = getToken();
  const [message, setMessage] = useState('');
  const [type, setType] = useState<'ok' | 'err'>('ok');
  const [orgs, setOrgs] = useState<any[]>([]);
  const [hosts, setHosts] = useState<any[]>([]);
  const [fields, setFields] = useState<any[]>([]);
  const [orgId, setOrgId] = useState('');
  const [hostId, setHostId] = useState('');
  const [fieldForm, setFieldForm] = useState({ name: '', layout_type: '', is_active: true });
  const [editingFieldId, setEditingFieldId] = useState<string | null>(null);

  const load = async () => {
    const [o, h, f] = await Promise.all([
      apiFetch('/organizations?page_size=500', {}, token),
      apiFetch('/host-locations?page_size=500', {}, token),
      apiFetch('/fields?page_size=2000', {}, token),
    ]);
    setOrgs((o as any).items || []);
    setHosts((h as any).items || []);
    setFields((f as any).items || []);
  };

  useEffect(() => { load().catch((e: any) => { setType('err'); setMessage(e.message || 'Failed to load'); }); }, []);

  const hostOptions = useMemo(() => hosts.filter((h: any) => !orgId || h.organization_id === orgId), [hosts, orgId]);
  const selectedHost = useMemo(() => hosts.find((h: any) => h.id === hostId), [hosts, hostId]);
  const fieldsByHost = useMemo(() => fields.reduce((map: any, field: any) => ({ ...map, [field.host_location_id]: [...(map[field.host_location_id] || []), field] }), {}), [fields]);
  const selectedHostFields = fieldsByHost[hostId] || [];
  const tableHosts = useMemo(() => hosts.filter((h: any) => (!orgId || h.organization_id === orgId) && (!hostId || h.id === hostId)), [hosts, orgId, hostId]);
  const orgNameById = useMemo(() => Object.fromEntries(orgs.map((org: any) => [org.id, org.name])), [orgs]);

  const onHostChange = (nextHostId: string) => {
    const host = hosts.find((h: any) => h.id === nextHostId);
    setHostId(nextHostId);
    if (host?.organization_id) setOrgId(host.organization_id);
    setFieldForm({ name: '', layout_type: '', is_active: true });
    setEditingFieldId(null);
  };

  const resetFieldForm = () => {
    setFieldForm({ name: '', layout_type: '', is_active: true });
    setEditingFieldId(null);
  };

  const editField = (field: any) => {
    setFieldForm({ name: field.name || '', layout_type: field.layout_type || '', is_active: Boolean(field.is_active) });
    setEditingFieldId(field.id);
  };

  const saveField = async () => {
    try {
      if (!selectedHost) { setType('err'); setMessage('Hosting site is required.'); return; }
      if (selectedHost.surface_type !== GRASS_FIELD) { setType('err'); setMessage('Manual fields are only available for Grass Field locations.'); return; }
      if (!fieldForm.name.trim()) { setType('err'); setMessage('Field name is required.'); return; }
      if (!FIELD_TYPES.includes(fieldForm.layout_type)) { setType('err'); setMessage('Every configured field must have a field type.'); return; }
      const payload = { host_location_id: selectedHost.id, physical_field_area_id: null, name: fieldForm.name.trim(), layout_type: fieldForm.layout_type, is_active: fieldForm.is_active, notes: null };
      if (editingFieldId) await apiFetch(`/fields/${editingFieldId}`, { method: 'PUT', body: JSON.stringify(payload) }, token);
      else await apiFetch('/fields', { method: 'POST', body: JSON.stringify(payload) }, token);
      setType('ok'); setMessage(editingFieldId ? 'Field updated.' : 'Field added.');
      resetFieldForm();
      await load();
    } catch (e: any) { setType('err'); setMessage(e.message || 'Save failed'); }
  };

  const deactivateField = async (field: any) => {
    try {
      await apiFetch(`/fields/${field.id}`, { method: 'PUT', body: JSON.stringify({ ...field, layout_type: field.layout_type, is_active: false }) }, token);
      setType('ok'); setMessage('Field deactivated. Inactive fields are not available for slot generation.');
      await load();
    } catch (e: any) { setType('err'); setMessage(e.message || 'Unable to deactivate field'); }
  };

  return <div className='space-y-4'>
    <Toast message={message} type={type} />
    <h1 className='text-2xl font-bold'>Host Location Field Configuration</h1>

    <section className='rounded border p-4'>
      <h2 className='mb-2 font-semibold'>1. Choose Host Location</h2>
      <div className='grid gap-2 md:grid-cols-2'>
        <select className='rounded border p-2' value={orgId} onChange={(e) => { setOrgId(e.target.value); setHostId(''); resetFieldForm(); }}>
          <option value=''>Select Organization</option>
          {orgs.map((org: any) => <option key={org.id} value={org.id}>{org.name}</option>)}
        </select>
        <select className='rounded border p-2' value={hostId} onChange={(e) => onHostChange(e.target.value)}>
          <option value=''>Select Hosting Site</option>
          {hostOptions.map((host: any) => <option key={host.id} value={host.id}>{host.name}</option>)}
        </select>
      </div>
      {selectedHost && <div className='mt-3 rounded bg-slate-100 px-3 py-2 text-sm font-medium'>Surface Type: {formatSurfaceType(selectedHost.surface_type)}</div>}
      {selectedHost && <p className='mt-2 text-sm text-slate-600'>Surface type is read-only here and is managed from Host Locations.</p>}
    </section>

    {selectedHost?.surface_type === TURF_STADIUM && <section className='rounded border p-4'>
      <h2 className='font-semibold'>Approved Turf Stadium Layouts</h2>
      <p className='text-sm text-slate-600'>All approved layouts that fit the 120-yard stadium footprint are supported automatically. These cards are read-only reference for scheduling capacity.</p>
      <div className='mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
        {TURF_LAYOUTS.map((layout) => <article key={layout.name} className='rounded border bg-slate-50 p-3 text-left'>
          <p className='font-semibold'>{layout.title}</p>
          <p className='mt-1 text-sm'>Space Used: {layout.spaceUsed} yards</p>
          <p className='text-sm'>Remaining: {layout.remaining} yards</p>
          <p className='text-sm'>Fields: {[layout.large ? `${layout.large} Large` : '', layout.medium ? `${layout.medium} Medium` : '', layout.small ? `${layout.small} Small` : ''].filter(Boolean).join(', ')}</p>
          <p className='mt-1 text-xs text-slate-600'>Supports: {supportedGroups(layout)}</p>
        </article>)}
      </div>
      <p className='mt-3 rounded bg-emerald-50 p-3 text-sm text-emerald-900'>All approved turf stadium layouts are available for this location. The scheduler will select the best layout for each host date unless a layout is locked in Hosting Availability.</p>
    </section>}

    {selectedHost?.surface_type === GRASS_FIELD && <section className='rounded border p-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div>
          <h2 className='font-semibold'>Manual Grass Field Setup</h2>
          <p className='text-sm text-slate-600'>Grass field locations use active configured fields for slot generation and must have at least one active field before hosting availability can use them.</p>
        </div>
        <button className='rounded border px-3 py-2 text-sm' onClick={resetFieldForm}>Add Field</button>
      </div>
      <div className='mt-3 grid gap-2 md:grid-cols-4'>
        <input className='rounded border p-2' placeholder='Field Name' value={fieldForm.name} onChange={(e) => setFieldForm({ ...fieldForm, name: e.target.value })} />
        <select className='rounded border p-2' value={fieldForm.layout_type} onChange={(e) => setFieldForm({ ...fieldForm, layout_type: e.target.value })}>
          <option value=''>Field Type</option>
          {FIELD_TYPES.map((fieldType) => <option key={fieldType} value={fieldType}>{fieldTypeLabel(fieldType)}</option>)}
        </select>
        <label className='flex items-center gap-2 rounded border p-2 text-sm'><input type='checkbox' checked={fieldForm.is_active} onChange={(e) => setFieldForm({ ...fieldForm, is_active: e.target.checked })} />Active</label>
        <button className='rounded bg-emerald-700 px-4 py-2 text-white' onClick={saveField}>{editingFieldId ? 'Update Field' : 'Add Field'}</button>
      </div>
      <div className='mt-4 overflow-x-auto'>
        <table className='w-full text-sm'>
          <thead><tr><th className='border p-2 text-left'>Field Name</th><th className='border p-2 text-left'>Field Type</th><th className='border p-2 text-left'>Active</th><th className='border p-2 text-left'>Actions</th></tr></thead>
          <tbody>{selectedHostFields.length ? selectedHostFields.map((field: any) => <tr key={field.id}><td className='border p-2'>{field.name}</td><td className='border p-2'>{fieldTypeLabel(field.layout_type)}</td><td className='border p-2'>{field.is_active ? 'Active' : 'Inactive'}</td><td className='border p-2'><div className='flex gap-2'><button className='rounded border px-2 py-1 text-xs' onClick={() => editField(field)}>Edit Field</button><button className='rounded border px-2 py-1 text-xs' disabled={!field.is_active} onClick={() => deactivateField(field)}>Deactivate Field</button></div></td></tr>) : <tr><td className='border p-3 text-center text-slate-500' colSpan={4}>No fields configured.</td></tr>}</tbody>
        </table>
      </div>
      <div className='mt-3 rounded bg-slate-50 p-3 text-xs text-slate-700'>
        <p className='font-semibold'>Division compatibility by field type</p>
        <p>Small: {DIVISION_COMPATIBILITY.SMALL.join(', ')}</p>
        <p>Medium: {DIVISION_COMPATIBILITY.MEDIUM.join(', ')}</p>
        <p>Large: {DIVISION_COMPATIBILITY.LARGE.join(', ')}</p>
      </div>
    </section>}

    <section className='rounded border p-4'>
      <h2 className='mb-2 font-semibold'>Current Hosting Site Setups</h2>
      <div className='overflow-x-auto'>
        <table className='w-full text-sm'>
          <thead><tr><th className='border p-2 text-left'>Organization</th><th className='border p-2 text-left'>Host Location</th><th className='border p-2 text-left'>Surface Type</th><th className='border p-2 text-left'>Available Layout / Configured Fields</th><th className='border p-2 text-left'>Large Fields</th><th className='border p-2 text-left'>Medium Fields</th><th className='border p-2 text-left'>Small Fields</th><th className='border p-2 text-left'>Status</th><th className='border p-2 text-left'>Actions</th></tr></thead>
          <tbody>{tableHosts.map((host: any) => {
            const hostFields = fieldsByHost[host.id] || [];
            const activeFields = hostFields.filter((field: any) => field.is_active);
            const surfaceType = host.surface_type || GRASS_FIELD;
            const counts = surfaceType === TURF_STADIUM ? { large: '0–2', medium: '0–2', small: '0–3' } : {
              large: activeFields.filter((field: any) => field.layout_type === 'LARGE').length,
              medium: activeFields.filter((field: any) => field.layout_type === 'MEDIUM').length,
              small: activeFields.filter((field: any) => field.layout_type === 'SMALL').length,
            };
            const isReady = surfaceType === TURF_STADIUM ? Boolean(host.is_active) : activeFields.length > 0;
            return <tr key={host.id}>
              <td className='border p-2'>{orgNameById[host.organization_id] || 'Unknown'}</td>
              <td className='border p-2'>{host.name}</td>
              <td className='border p-2'>{formatSurfaceType(surfaceType)}</td>
              <td className='border p-2'>{surfaceType === TURF_STADIUM ? 'All approved turf stadium layouts' : configuredFieldsText(activeFields.length)}</td>
              <td className='border p-2'>{counts.large}</td><td className='border p-2'>{counts.medium}</td><td className='border p-2'>{counts.small}</td>
              <td className='border p-2'>{isReady ? 'Active' : 'Needs setup'}</td>
              <td className='border p-2'><button className='rounded border px-2 py-1 text-xs' onClick={() => onHostChange(host.id)}>Edit</button></td>
            </tr>;
          })}</tbody>
        </table>
      </div>
    </section>
  </div>;
}
