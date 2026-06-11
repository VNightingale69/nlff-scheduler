'use client';
import { useEffect, useMemo, useState } from 'react';
import Toast from './Toast';
import { apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';
import { APPROVED_TURF_CONFIGURATIONS, turfAvailableFieldsLabel, turfConfigurationLabel, type TurfConfiguration } from '@/lib/turfConfigurations';

const TURF_STADIUM = 'TURF_STADIUM';
const GRASS_FIELD = 'GRASS_FIELD';
type FieldType = 'SMALL' | 'MEDIUM' | 'LARGE';
const FIELD_TYPES = ['SMALL', 'MEDIUM', 'LARGE'];
const FACILITY_TYPES = [
  { value: TURF_STADIUM, label: 'Turf Stadium', fieldSize: undefined },
  { value: 'LARGE_GRASS_FIELD', label: 'Large Grass Field', fieldSize: 'LARGE' },
  { value: 'MEDIUM_GRASS_FIELD', label: 'Medium Grass Field', fieldSize: 'MEDIUM' },
  { value: 'SMALL_GRASS_FIELD', label: 'Small Grass Field', fieldSize: 'SMALL' },
];

const DIVISION_COMPATIBILITY: Record<FieldType, string[]> = {
  SMALL: ['Coed K-1', 'Coed 2-3', 'Girls K-2'],
  MEDIUM: ['Coed 4-5', 'Girls 3-5'],
  LARGE: ['Coed 6-7', 'Coed 8', 'Girls 6-8'],
};

type FieldAreaLayout = {
  name?: string;
  code?: string;
  title?: string;
  displayName?: string;
  fields?: string[];
  availableFields?: TurfConfiguration['availableFields'];
  supportedDivisions?: string[];
  large?: number;
  medium?: number;
  small?: number;
  fieldType?: string;
  field_type?: string;
  type?: string;
  required_field_layout_type?: string;
  schedulingNote?: string;
};

const TURF_LAYOUTS: FieldAreaLayout[] = APPROVED_TURF_CONFIGURATIONS.map((config) => ({
  name: config.code,
  code: config.code,
  title: config.displayName,
  displayName: config.displayName,
  availableFields: config.availableFields,
  fields: config.availableFields.map((fieldType) => `${fieldType.charAt(0)}${fieldType.slice(1).toLowerCase()}`),
  supportedDivisions: config.supportedDivisions,
  large: config.availableFields.filter((fieldType) => fieldType === 'LARGE').length,
  medium: config.availableFields.filter((fieldType) => fieldType === 'MEDIUM').length,
  small: config.availableFields.filter((fieldType) => fieldType === 'SMALL').length,
  schedulingNote: config.schedulingNote,
}));
const APPROVED_TURF_LAYOUT_CODES = new Set(TURF_LAYOUTS.map((layout) => layout.name));

const formatSurfaceType = (value?: string) => value === TURF_STADIUM ? 'Turf Stadium' : value === GRASS_FIELD ? 'Grass Field' : 'Not set';
const _fieldTypeLabel = (value?: string) => value ? value.charAt(0).toUpperCase() + value.slice(1).toLowerCase() : '—';
const facilityTypeLabel = (value?: string) => FACILITY_TYPES.find((option) => option.value === value)?.label || 'Not set';
const grassFacilityTypeForSize = (value?: string) => `${_fieldTypeLabel(value)} Grass Field`;
const fieldTypeLabel = _fieldTypeLabel;
const configuredFieldsText = (count: number) => `${count} active configured field${count === 1 ? '' : 's'}`;
const configLabel = (value?: string) => turfConfigurationLabel(value);
const errorMessage = (error: any, fallback: string) => error?.message || fallback;

const normalizeFieldType = (value?: string | null): FieldType | undefined => {
  const normalized = String(value || '').toUpperCase();
  return FIELD_TYPES.includes(normalized as FieldType) ? normalized as FieldType : undefined;
};

const fieldTypesForLayout = (layout?: FieldAreaLayout | null): FieldType[] => {
  if (!layout) return [];

  const explicitType = normalizeFieldType(layout.fieldType || layout.field_type || layout.type || layout.required_field_layout_type);
  if (explicitType) return [explicitType];

  const fieldTypes = [
    ...(layout.availableFields || []),
    ...(layout.fields || []).map((field) => normalizeFieldType(field)),
  ].filter(Boolean) as FieldType[];

  if (fieldTypes.length) return fieldTypes;

  return [
    ...Array(Math.max(0, layout.small || 0)).fill('SMALL'),
    ...Array(Math.max(0, layout.medium || 0)).fill('MEDIUM'),
    ...Array(Math.max(0, layout.large || 0)).fill('LARGE'),
  ] as FieldType[];
};

const supportedGroups = (layout?: FieldAreaLayout | null): string => {
  if (layout?.supportedDivisions?.length) return layout.supportedDivisions.join(', ');

  const divisions = Array.from(new Set(fieldTypesForLayout(layout).flatMap((fieldType) => DIVISION_COMPATIBILITY[fieldType] || [])));
  return divisions.length ? divisions.join(', ') : 'Configured divisions';
};

const layoutFieldsLabel = (layout?: FieldAreaLayout | null): string => {
  const availableFields = layout?.availableFields || fieldTypesForLayout(layout);
  if (availableFields.length) return turfAvailableFieldsLabel(availableFields);
  return (layout?.fields || []).join(' + ') || 'Configured fields';
};

const schedulingNote = (layout?: FieldAreaLayout | null): string => layout?.schedulingNote || 'Scheduling rules use the configured field layout metadata.';



export default function FieldAreaManager() {
  const { accessToken: token, currentUser: authUser } = useAuthSession();
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
      setType('ok'); setMessage('Field deactivated. Existing scheduled games keep this field, but inactive fields are not available for future slot generation.');
      await loadOrgData(orgId, hostId);
    } catch (e: any) { setType('err'); setMessage(e.message || 'Unable to deactivate field'); }
  };

  const deleteField = async (field: any) => {
    try {
      const impact = await apiFetch(`/fields/${field.id}/delete-impact`, {}, token) as any;
      const scheduledCount = Number(impact?.affected_scheduled_games_count || 0);
      const availabilityCount = Number(impact?.affected_hosting_availability_count || 0);
      const generatedSlotCount = Number(impact?.affected_generated_slots_count || 0);
      const communityName = impact?.community?.name || orgNameById[selectedHost?.organization_id] || 'Unknown community';
      const hostName = impact?.host_location?.name || selectedHost?.name || 'Unknown host location';
      const warning = scheduledCount > 0
        ? `This field is assigned to ${scheduledCount} scheduled game(s). Deleting it will remove the field from those games and flag them as missing a field assignment. Continue?`
        : 'Delete this field? This will remove the field from active use. Any scheduled games currently assigned to this field will remain scheduled but will be flagged as missing a field assignment and must be reviewed.';
      const details = [
        warning,
        '',
        `Field: ${field.name}`,
        `Host location: ${hostName}`,
        `Community: ${communityName}`,
        `Scheduled games affected: ${scheduledCount}`,
        `Future hosting availability records affected: ${availabilityCount}`,
        `Generated slots affected: ${generatedSlotCount}`,
      ].join('\n');
      if (!window.confirm(details)) return;
      const response = await apiFetch(`/fields/${field.id}`, { method: 'DELETE' }, token) as any;
      const affected = Number(response?.affected_scheduled_games_count ?? scheduledCount);
      setType('ok');
      setMessage(`Field deleted. ${affected} scheduled game(s) were flagged as missing a field assignment.${affected ? ' Review affected games in Manual Schedule Builder using the Missing Field filter.' : ''}`);
      if (editingFieldId === field.id) resetFieldForm();
      await loadOrgData(orgId, hostId);
    } catch (e: any) { setType('err'); setMessage(e.message || 'Unable to delete field'); }
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
      const maxFieldsPerWave = surfaceType === TURF_STADIUM ? Math.max(...TURF_LAYOUTS.map((layout) => fieldTypesForLayout(layout).length)) : 0;
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
      <p className='mt-1 text-sm text-slate-600'>Choose the business-friendly facility type for this host location. Field sizes are consistent across all locations: Small, Medium, and Large.</p>
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
          <p className='text-sm'>{layoutFieldsLabel(layout)}</p>
          <p className='mt-2 text-xs font-semibold uppercase text-slate-500'>Supported Divisions</p>
          <p className='text-sm'>{supportedGroups(layout)}</p>
          <p className='mt-2 text-xs font-semibold uppercase text-slate-500'>Scheduling Note</p>
          <p className='text-sm'>{schedulingNote(layout)}</p>
        </article>)}
      </div>
      <p className='mt-3 rounded bg-emerald-50 p-3 text-sm text-emerald-900'>This turf location supports the four approved league turf configurations. During scheduling, each one-hour wave will be assigned one approved configuration code. Unused field slots are allowed when there are not enough compatible games to fill the selected layout.</p>
    </section>}

    {selectedHost?.surface_type === GRASS_FIELD && <section className='rounded border p-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div>
          <h2 className='font-semibold'>Grass Field Setup Guidance</h2>
          <p className='text-sm text-slate-600'>Field sizes are consistent across all locations: Small, Medium, and Large. For grass locations, each configured field should represent a field that can realistically be used during the same one-hour game block at that location. Only add fields that can be played at the same time based on available space, lining, staffing, equipment, parking, and field overlap.</p>
          <ul className='mt-2 list-disc pl-5 text-xs text-slate-600'>
            <li>If the location can support three Small fields at the same time, add Small Field 1, Small Field 2, and Small Field 3.</li>
            <li>If the location can support two Large fields at the same time, add Large Field 1 and Large Field 2.</li>
            <li>If a Large field layout overlaps with Small fields and they cannot be used at the same time, do not configure those overlapping fields as simultaneously active.</li>
            <li>If a field exists physically but cannot be lined, staffed, equipped, or operated during a one-hour block, do not mark it active.</li>
          </ul>
          <p className='mt-2 text-xs text-slate-600'>Grass field locations use active configured fields for slot generation and must have at least one active field before hosting availability can use them. Deactivate keeps existing scheduled assignments; Delete removes the field from active use and flags affected scheduled games for Scheduling Administrator review.</p>
        </div>
        <button className='rounded border px-3 py-2 text-sm' onClick={resetFieldForm}>Add Field</button>
      </div>
      <p className='mt-3 text-sm font-medium text-slate-700'>Add only fields that this location can support during the same one-hour block.</p>
      <div className='mt-2 grid gap-2 md:grid-cols-4'>
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
          <tbody>{fieldLoadError ? <tr><td className='border p-3 text-center text-rose-700' colSpan={4}>Field configurations failed to load: {fieldLoadError}</td></tr> : selectedHostFields.length ? selectedHostFields.map((field: any) => <tr key={field.id}><td className='border p-2'>{field.name}</td><td className='border p-2'>{fieldTypeLabel(field.layout_type)}</td><td className='border p-2'>{field.is_active ? 'Active' : 'Inactive'}</td><td className='border p-2'><div className='flex gap-2'><button className='rounded border px-2 py-1 text-xs' onClick={() => { setFieldForm({ name: field.name || '', layout_type: field.layout_type || '', is_active: Boolean(field.is_active) }); setEditingFieldId(field.id); }}>Edit Field</button><button className='rounded border px-2 py-1 text-xs' disabled={!field.is_active} onClick={() => deactivateField(field)}>Deactivate Field</button><button className='rounded border border-rose-700 bg-rose-600 px-2 py-1 text-xs font-semibold text-white hover:bg-rose-700' onClick={() => deleteField(field)}>Delete Field</button></div></td></tr>) : <tr><td className='border p-3 text-center text-slate-500' colSpan={4}>No fields configured.</td></tr>}</tbody>
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
          <thead>{isCommunityAdmin ? <tr><th className='border p-2 text-left'>Organization / Community</th><th className='border p-2 text-left'>Host Location</th><th className='border p-2 text-left'>Facility Type</th><th className='border p-2 text-left'>Status</th><th className='border p-2 text-left'>Actions</th></tr> : tableHosts.length > 0 && tableHosts.every((host: any) => (host.surface_type || GRASS_FIELD) !== TURF_STADIUM) ? <tr><th className='border p-2 text-left'>Organization</th><th className='border p-2 text-left'>Host Location</th><th className='border p-2 text-left'>Surface Type</th><th className='border p-2 text-left'>Active Configured Fields</th><th className='border p-2 text-left'>Large Fields</th><th className='border p-2 text-left'>Medium Fields</th><th className='border p-2 text-left'>Small Fields</th><th className='border p-2 text-left'>Status</th><th className='border p-2 text-left'>Actions</th></tr> : <tr><th className='border p-2 text-left'>Organization</th><th className='border p-2 text-left'>Host Location</th><th className='border p-2 text-left'>Surface Type</th><th className='border p-2 text-left'>Active Layouts / Configured Fields</th><th className='border p-2 text-left'>Turf Layout Count / Large Fields</th><th className='border p-2 text-left'>Max Fields Per Hour / Medium Fields</th><th className='border p-2 text-left'>Turf Surface / Small Fields</th><th className='border p-2 text-left'>Status</th><th className='border p-2 text-left'>Actions</th></tr>}</thead>
          <tbody>{renderSetupRows()}</tbody>
        </table>
      </div>
    </section>
  </div>;
}
