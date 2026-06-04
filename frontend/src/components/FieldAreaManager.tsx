'use client';
import { useEffect, useMemo, useState } from 'react';
import Toast from './Toast';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';

const TURF_STADIUM = 'TURF_STADIUM';
const GRASS_FIELD = 'GRASS_FIELD';
const FIELD_TYPES = ['SMALL', 'MEDIUM', 'LARGE'];
const FACILITY_TYPES = [
  { value: TURF_STADIUM, label: 'Turf Stadium', fieldSize: undefined },
  { value: 'LARGE_GRASS_FIELD', label: 'Large Grass Field', fieldSize: 'LARGE' },
  { value: 'MEDIUM_GRASS_FIELD', label: 'Medium Grass Field', fieldSize: 'MEDIUM' },
  { value: 'SMALL_GRASS_FIELD', label: 'Small Grass Field', fieldSize: 'SMALL' },
];

const DIVISION_COMPATIBILITY = {
  SMALL: ['Coed K-1', 'Coed 2-3', 'Girls K-2'],
  MEDIUM: ['Coed 4-5', 'Girls 3-5'],
  LARGE: ['Coed 6-7', 'Coed 8', 'Girls 6-8'],
};

const TURF_LAYOUTS = [
  { name: 'THREE_SMALL', title: 'Three Small Fields', fields: ['Small', 'Small', 'Small'], large: 0, medium: 0, small: 3, schedulingNote: 'Best for one-hour waves with small-division demand.' },
  { name: 'TWO_SMALL_ONE_MEDIUM', title: 'Two Small Fields + One Medium Field', fields: ['Small', 'Small', 'Medium'], large: 0, medium: 1, small: 2, schedulingNote: 'Supports small and medium games in the same one-hour wave.' },
  { name: 'TWO_MEDIUM', title: 'Two Medium Fields', fields: ['Medium', 'Medium'], large: 0, medium: 2, small: 0, schedulingNote: 'Best for one-hour waves with medium-division demand.' },
  { name: 'ONE_SMALL_ONE_LARGE', title: 'One Small Field + One Large Field', fields: ['Small', 'Large'], large: 1, medium: 0, small: 1, schedulingNote: 'Supports large games while allowing one compatible small game in the same one-hour wave.' },
];
const APPROVED_TURF_LAYOUT_CODES = new Set(TURF_LAYOUTS.map((layout) => layout.name));

const formatSurfaceType = (value?: string) => value === TURF_STADIUM ? 'Turf Stadium' : value === GRASS_FIELD ? 'Grass Field' : 'Not set';
const _fieldTypeLabel = (value?: string) => value ? value.charAt(0).toUpperCase() + value.slice(1).toLowerCase() : '—';
const facilityTypeLabel = (value?: string) => FACILITY_TYPES.find((option) => option.value === value)?.label || 'Not set';
const grassFacilityTypeForSize = (value?: string) => `${_fieldTypeLabel(value)} Grass Field`;
const fieldTypeLabel = _fieldTypeLabel;
const configuredFieldsText = (count: number) => `${count} active configured field${count === 1 ? '' : 's'}`;
const configLabel = (value?: string) => {
  const layout = TURF_LAYOUTS.find((item) => item.name === value);
  return layout ? `${layout.name} — ${layout.title}` : value || 'Unknown layout';
};
const errorMessage = (error: any, fallback: string) => error?.message || fallback;

const supportedGroups = (layout: typeof TURF_LAYOUTS[number]) => {
  const groups: string[] = [];
  if (layout.small) groups.push('Coed K-1', 'Coed 2-3', 'Girls K-2');
  if (layout.medium) groups.push('Coed 4-5', 'Girls 3-5');
  if (layout.large) groups.push('Coed 6-7', 'Coed 8', 'Girls 6-8');
  return groups.join(', ');
};

export default function FieldAreaManager() {
  const token = getToken();
  const authUser = getAuthUser();
  const isCommunityAdmin = authUser?.role_name === 'COMMUNITY_ADMIN';
  const [message, setMessage] = useState('');
  const [type, setType] = useState<'ok' | 'err'>('ok');
  const [orgs, setOrgs] = useState<any[]>([]);
  const [hosts, setHosts] = useState<any[]>([]);
  const [fields, setFields] = useState<any[]>([]);
  const [hostConfigs, setHostConfigs] = useState<any[]>([]);
  const [orgId, setOrgId] = useState('');
  const [hostId, setHostId] = useState('');
  const [loadingOrgData, setLoadingOrgData] = useState(false);
  const [hostLoadError, setHostLoadError] = useState('');
  const [fieldLoadError, setFieldLoadError] = useState('');
  const [fieldForm, setFieldForm] = useState({ name: '', layout_type: '', is_active: true });
  const [editingFieldId, setEditingFieldId] = useState<string | null>(null);
  const [facilityForm, setFacilityForm] = useState('');
  const [savingFacility, setSavingFacility] = useState(false);

  const resetFieldForm = () => {
    setFieldForm({ name: '', layout_type: '', is_active: true });
    setEditingFieldId(null);
  };

  const loadOrganizations = async () => {
    const data = await apiFetch('/organizations?page_size=500', {}, token);
    const items = (data as any).items || [];
    setOrgs(items);
    if (items.length === 1) setOrgId(items[0].id);
  };

  const loadOrgData = async (nextOrgId: string, nextHostId = '') => {
    setHostLoadError('');
    setFieldLoadError('');
    setHosts([]);
    setFields([]);
    setHostConfigs([]);
    if (!nextOrgId) return;

    setLoadingOrgData(true);
    const query = nextHostId ? `host_location_id=${encodeURIComponent(nextHostId)}` : `organization_id=${encodeURIComponent(nextOrgId)}`;
    const hostQuery = `organization_id=${encodeURIComponent(nextOrgId)}&page_size=2000`;
    let hostRequestFailed = false;

    try {
      const hostData = await apiFetch(`/host-locations?${hostQuery}`, {}, token);
      setHosts((hostData as any).items || []);
    } catch (e: any) {
      hostRequestFailed = true;
      const msg = errorMessage(e, 'Failed to load hosting sites.');
      setHostLoadError(msg);
      setType('err');
      setMessage(msg);
    }

    try {
      const [fieldData, configData] = await Promise.all([
        apiFetch(`/fields?${query}&page_size=5000`, {}, token),
        apiFetch(`/host-location-configurations?${query}&page_size=5000`, {}, token),
      ]);
      setFields((fieldData as any).items || []);
      setHostConfigs((configData as any).items || []);
    } catch (e: any) {
      const msg = errorMessage(e, 'Failed to load field configurations.');
      setFieldLoadError(msg);
      setType('err');
      setMessage(msg);
    } finally {
      setLoadingOrgData(false);
    }

    if (!hostRequestFailed) setHostLoadError('');
  };

  useEffect(() => { loadOrganizations().catch((e: any) => { setType('err'); setMessage(errorMessage(e, 'Failed to load organizations.')); }); }, []);
  useEffect(() => { loadOrgData(orgId, hostId); }, [orgId, hostId]);

  const hostOptions = useMemo(() => hosts.filter((h: any) => !orgId || h.organization_id === orgId), [hosts, orgId]);
  const selectedHost = useMemo(() => hosts.find((h: any) => h.id === hostId), [hosts, hostId]);
  const fieldsByHost = useMemo(() => fields.reduce((map: any, field: any) => ({ ...map, [field.host_location_id]: [...(map[field.host_location_id] || []), field] }), {}), [fields]);
  const hostConfigsByHost = useMemo(() => hostConfigs.reduce((map: any, config: any) => ({ ...map, [config.host_location_id]: [...(map[config.host_location_id] || []), config] }), {}), [hostConfigs]);
  const facilityTypeForHost = (host: any) => {
    const surfaceType = host?.surface_type || GRASS_FIELD;
    if (surfaceType === TURF_STADIUM) return TURF_STADIUM;
    const activeFields = (fieldsByHost[host?.id] || []).filter((field: any) => field.is_active);
    const fixedSize = activeFields.find((field: any) => FIELD_TYPES.includes(field.layout_type))?.layout_type;
    return fixedSize ? `${fixedSize}_GRASS_FIELD` : '';
  };
  const selectedHostFields = fieldsByHost[hostId] || [];
  const tableHosts = useMemo(() => hosts.filter((h: any) => (!orgId || h.organization_id === orgId) && (!hostId || h.id === hostId)), [hosts, orgId, hostId]);
  const orgNameById = useMemo(() => Object.fromEntries(orgs.map((org: any) => [org.id, org.name])), [orgs]);

  useEffect(() => {
    setFacilityForm(selectedHost ? facilityTypeForHost(selectedHost) : '');
  }, [selectedHost, fieldsByHost]);

  const onOrgChange = (nextOrgId: string) => {
    setOrgId(nextOrgId);
    setHostId('');
    resetFieldForm();
  };

  const onHostChange = (nextHostId: string) => {
    const host = hosts.find((h: any) => h.id === nextHostId);
    setHostId(nextHostId);
    if (host?.organization_id) setOrgId(host.organization_id);
    resetFieldForm();
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
      await loadOrgData(orgId, hostId);
    } catch (e: any) { setType('err'); setMessage(e.message || 'Save failed'); }
  };

  const deactivateField = async (field: any) => {
    try {
      await apiFetch(`/fields/${field.id}`, { method: 'PUT', body: JSON.stringify({ ...field, layout_type: field.layout_type, is_active: false }) }, token);
      setType('ok'); setMessage('Field deactivated. Inactive fields are not available for slot generation.');
      await loadOrgData(orgId, hostId);
    } catch (e: any) { setType('err'); setMessage(e.message || 'Unable to deactivate field'); }
  };

  const hostPayload = (host: any, surfaceType: string, fieldSize?: string) => ({
    organization_id: host.organization_id,
    name: host.name,
    address: host.address || null,
    address_line1: host.address_line1 || host.address || null,
    address_line2: host.address_line2 || null,
    city: host.city || null,
    state: host.state || null,
    zip_code: host.zip_code || null,
    surface_type: surfaceType,
    max_small_fields: fieldSize === 'SMALL' ? 1 : 0,
    max_medium_fields: fieldSize === 'MEDIUM' ? 1 : 0,
    max_large_fields: fieldSize === 'LARGE' ? 1 : 0,
    max_total_fields: fieldSize ? 1 : 0,
    notes: host.notes || null,
    is_active: host.is_active !== false,
  });

  const saveFacilityType = async () => {
    try {
      if (!selectedHost) { setType('err'); setMessage('Hosting site is required.'); return; }
      if (!facilityForm) { setType('err'); setMessage('Facility type is required.'); return; }
      setSavingFacility(true);
      if (facilityForm === TURF_STADIUM) {
        await apiFetch(`/host-locations/${selectedHost.id}`, { method: 'PUT', body: JSON.stringify(hostPayload(selectedHost, TURF_STADIUM)) }, token);
        setType('ok'); setMessage('Facility saved as Turf Stadium. The scheduler will choose the best layout for each hosting date.');
      } else {
        const fieldSize = FACILITY_TYPES.find((option) => option.value === facilityForm)?.fieldSize;
        if (!fieldSize) { setType('err'); setMessage('Select a valid grass field size.'); return; }
        await apiFetch(`/host-locations/${selectedHost.id}`, { method: 'PUT', body: JSON.stringify(hostPayload(selectedHost, GRASS_FIELD, fieldSize)) }, token);
        const activeFields = selectedHostFields.filter((field: any) => field.is_active);
        const primaryField = activeFields[0] || selectedHostFields[0];
        const fieldPayload = { host_location_id: selectedHost.id, physical_field_area_id: primaryField?.physical_field_area_id || null, name: primaryField?.name || selectedHost.name, layout_type: fieldSize, is_active: true, notes: primaryField?.notes || null };
        if (primaryField) await apiFetch(`/fields/${primaryField.id}`, { method: 'PUT', body: JSON.stringify(fieldPayload) }, token);
        else await apiFetch('/fields', { method: 'POST', body: JSON.stringify(fieldPayload) }, token);
        for (const extraField of activeFields.slice(1)) {
          await apiFetch(`/fields/${extraField.id}`, { method: 'PUT', body: JSON.stringify({ ...extraField, is_active: false }) }, token);
        }
        setType('ok'); setMessage(`Facility saved as ${facilityTypeLabel(facilityForm)}.`);
      }
      await loadOrgData(orgId, hostId);
    } catch (e: any) { setType('err'); setMessage(e.message || 'Facility save failed'); }
    finally { setSavingFacility(false); }
  };

  const renderSetupRows = () => {
    const colSpan = isCommunityAdmin ? 5 : 9;
    if (!orgId) return <tr><td className='border p-3 text-center text-slate-500' colSpan={colSpan}>Select an organization to view hosting site setups.</td></tr>;
    if (hostLoadError || fieldLoadError) return <tr><td className='border p-3 text-center text-rose-700' colSpan={colSpan}>Unable to load setup data. {hostLoadError || fieldLoadError}</td></tr>;
    if (loadingOrgData) return <tr><td className='border p-3 text-center text-slate-500' colSpan={colSpan}>Loading hosting site setups…</td></tr>;
    if (!tableHosts.length) return <tr><td className='border p-3 text-center text-slate-500' colSpan={colSpan}>No hosting sites have been added for this community.</td></tr>;

    return tableHosts.map((host: any) => {
      const hostFields = fieldsByHost[host.id] || [];
      const activeFields = hostFields.filter((field: any) => field.is_active);
      const activeConfigs = (hostConfigsByHost[host.id] || []).filter((config: any) => config.is_active && APPROVED_TURF_LAYOUT_CODES.has(config.configuration_name));
      const surfaceType = host.surface_type || GRASS_FIELD;
      const grassCounts = {
        large: activeFields.filter((field: any) => field.layout_type === 'LARGE').length,
        medium: activeFields.filter((field: any) => field.layout_type === 'MEDIUM').length,
        small: activeFields.filter((field: any) => field.layout_type === 'SMALL').length,
      };
      const maxFieldsPerWave = surfaceType === TURF_STADIUM ? Math.max(...TURF_LAYOUTS.map((layout) => layout.fields.length)) : 0;
      const isReady = surfaceType === TURF_STADIUM ? Boolean(host.is_active) : activeFields.length > 0;
      if (isCommunityAdmin) {
        return <tr key={host.id}>
          <td className='border p-2'>{orgNameById[host.organization_id] || 'Unknown'}</td>
          <td className='border p-2'>{host.name}</td>
          <td className='border p-2'>{surfaceType === TURF_STADIUM ? 'Turf Stadium' : (activeFields[0]?.layout_type ? grassFacilityTypeForSize(activeFields[0].layout_type) : 'Grass Field')}</td>
          <td className='border p-2'>{isReady ? 'Active' : 'Needs setup'}</td>
          <td className='border p-2'><button className='rounded border px-2 py-1 text-xs' onClick={() => onHostChange(host.id)}>Edit</button></td>
        </tr>;
      }
      return <tr key={host.id}>
        <td className='border p-2'>{orgNameById[host.organization_id] || 'Unknown'}</td>
        <td className='border p-2'>{host.name}</td>
        <td className='border p-2'>{formatSurfaceType(surfaceType)}</td>
        {surfaceType === TURF_STADIUM ? <>
          <td className='border p-2'>{activeConfigs.length ? activeConfigs.map((config: any) => configLabel(config.configuration_name)).join(', ') : 'No active turf layouts'}</td>
          <td className='border p-2'>{activeConfigs.length}</td>
          <td className='border p-2'>{maxFieldsPerWave}</td>
          <td className='border p-2'>{formatSurfaceType(surfaceType)}</td>
        </> : <>
          <td className='border p-2'>{configuredFieldsText(activeFields.length)}</td>
          <td className='border p-2'>{grassCounts.large}</td><td className='border p-2'>{grassCounts.medium}</td><td className='border p-2'>{grassCounts.small}</td>
        </>}
        <td className='border p-2'>{isReady ? 'Active' : 'Needs setup'}</td>
        <td className='border p-2'><button className='rounded border px-2 py-1 text-xs' onClick={() => onHostChange(host.id)}>Edit</button></td>
      </tr>;
    });
  };

  return <div className='space-y-4'>
    <Toast message={message} type={type} />
    <h1 className='text-2xl font-bold'>Host Location Field Configuration</h1>

    <section className='rounded border p-4'>
      <h2 className='mb-2 font-semibold'>1. Choose Host Location</h2>
      <div className='grid gap-2 md:grid-cols-2'>
        <select className='rounded border p-2' value={orgId} onChange={(e) => onOrgChange(e.target.value)}>
          <option value=''>Select Organization</option>
          {orgs.map((org: any) => <option key={org.id} value={org.id}>{org.name}</option>)}
        </select>
        <select className='rounded border p-2' value={hostId} onChange={(e) => onHostChange(e.target.value)} disabled={!orgId || Boolean(hostLoadError) || !hostOptions.length}>
          <option value=''>Select Hosting Site</option>
          {hostOptions.map((host: any) => <option key={host.id} value={host.id}>{host.name}</option>)}
        </select>
      </div>
      {hostLoadError && <p className='mt-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800'>Hosting sites failed to load: {hostLoadError}</p>}
      {fieldLoadError && <p className='mt-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800'>Field configurations failed to load: {fieldLoadError}</p>}
      {orgId && !hostLoadError && !loadingOrgData && !hostOptions.length && <p className='mt-3 rounded bg-slate-100 p-3 text-sm text-slate-700'>No hosting sites have been added for this community.</p>}
      {!isCommunityAdmin && selectedHost && <div className='mt-3 rounded bg-slate-100 px-3 py-2 text-sm font-medium'>Surface Type: {formatSurfaceType(selectedHost.surface_type)}</div>}
      {!isCommunityAdmin && selectedHost && <p className='mt-2 text-sm text-slate-600'>Surface type is read-only here and is managed from Host Locations.</p>}
    </section>

    {isCommunityAdmin && selectedHost && <section className='rounded border p-4'>
      <h2 className='font-semibold'>Facility Type</h2>
      <p className='mt-1 text-sm text-slate-600'>Choose the business-friendly facility type for this host location. Grass fields stay fixed at the size you select.</p>
      <p className='mt-2 rounded bg-emerald-50 p-3 text-sm text-emerald-900'>For turf stadiums, select Turf Stadium only. The application will determine the best field layout for each hosting date during scheduling.</p>
      <div className='mt-3 grid gap-2 md:grid-cols-[1fr_auto]'>
        <select className='rounded border p-2' value={facilityForm} onChange={(e) => setFacilityForm(e.target.value)}>
          <option value=''>Select Facility Type</option>
          {FACILITY_TYPES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-50' onClick={saveFacilityType} disabled={savingFacility}>{savingFacility ? 'Saving…' : 'Save Facility Type'}</button>
      </div>
    </section>}

    {!isCommunityAdmin && selectedHost?.surface_type === TURF_STADIUM && <section className='rounded border p-4'>
      <h2 className='font-semibold'>Approved Turf Stadium Layouts</h2>
      <p className='text-sm text-slate-600'>Only league-approved turf configurations are supported. The scheduler assigns one approved configuration code per turf field per one-hour wave and then fills as many compatible game slots as practical.</p>
      <div className='mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3'>
        {TURF_LAYOUTS.map((layout) => <article key={layout.name} className='rounded border bg-slate-50 p-3 text-left'>
          <p className='text-xs font-semibold uppercase text-slate-500'>Configuration Code</p>
          <p className='font-semibold'>{layout.name}</p>
          <p className='mt-2 text-xs font-semibold uppercase text-slate-500'>Display Name</p>
          <p className='text-sm'>{layout.title}</p>
          <p className='mt-2 text-xs font-semibold uppercase text-slate-500'>Available Fields</p>
          <p className='text-sm'>{layout.fields.join(' + ')}</p>
          <p className='mt-2 text-xs font-semibold uppercase text-slate-500'>Supported Divisions</p>
          <p className='text-sm'>{supportedGroups(layout)}</p>
          <p className='mt-2 text-xs font-semibold uppercase text-slate-500'>Scheduling Note</p>
          <p className='text-sm'>{layout.schedulingNote}</p>
        </article>)}
      </div>
      <p className='mt-3 rounded bg-emerald-50 p-3 text-sm text-emerald-900'>This turf location supports the four approved league turf configurations. During scheduling, each one-hour wave will be assigned one approved configuration code. Unused field slots are allowed when there are not enough compatible games to fill the selected layout.</p>
    </section>}

    {!isCommunityAdmin && selectedHost?.surface_type === GRASS_FIELD && <section className='rounded border p-4'>
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
          <tbody>{fieldLoadError ? <tr><td className='border p-3 text-center text-rose-700' colSpan={4}>Field configurations failed to load: {fieldLoadError}</td></tr> : selectedHostFields.length ? selectedHostFields.map((field: any) => <tr key={field.id}><td className='border p-2'>{field.name}</td><td className='border p-2'>{fieldTypeLabel(field.layout_type)}</td><td className='border p-2'>{field.is_active ? 'Active' : 'Inactive'}</td><td className='border p-2'><div className='flex gap-2'><button className='rounded border px-2 py-1 text-xs' onClick={() => { setFieldForm({ name: field.name || '', layout_type: field.layout_type || '', is_active: Boolean(field.is_active) }); setEditingFieldId(field.id); }}>Edit Field</button><button className='rounded border px-2 py-1 text-xs' disabled={!field.is_active} onClick={() => deactivateField(field)}>Deactivate Field</button></div></td></tr>) : <tr><td className='border p-3 text-center text-slate-500' colSpan={4}>No fields configured.</td></tr>}</tbody>
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
      <h2 className='mb-2 font-semibold'>Current Facility Setups</h2>
      <div className='overflow-x-auto'>
        <table className='w-full text-sm'>
          <thead>{isCommunityAdmin ? <tr><th className='border p-2 text-left'>Organization / Community</th><th className='border p-2 text-left'>Host Location</th><th className='border p-2 text-left'>Facility Type</th><th className='border p-2 text-left'>Status</th><th className='border p-2 text-left'>Actions</th></tr> : <tr><th className='border p-2 text-left'>Organization</th><th className='border p-2 text-left'>Host Location</th><th className='border p-2 text-left'>Facility Summary</th><th className='border p-2 text-left'>Available Layout / Configured Fields</th><th className='border p-2 text-left'>Approved Configurations / Large Fields</th><th className='border p-2 text-left'>Max Fields Per Wave / Medium Fields</th><th className='border p-2 text-left'>Surface Type / Small Fields</th><th className='border p-2 text-left'>Status</th><th className='border p-2 text-left'>Actions</th></tr>}</thead>
          <tbody>{renderSetupRows()}</tbody>
        </table>
      </div>
    </section>
  </div>;
}
