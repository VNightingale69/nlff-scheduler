'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { ApiError, apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';
import Toast from '@/components/Toast';
import CommunityLogo from '@/components/CommunityLogo';
import FormField from '@/components/ui/FormField';

type Organization = {
  id: string;
  name: string;
  is_active: boolean;
  logo_url?: string | null;
  logo_filename?: string | null;
  logo_content_type?: string | null;
  logo_file_size?: number | null;
  logo_width?: number | null;
  logo_height?: number | null;
  logo_uploaded_at?: string | null;
};
type DeleteDependencyErrorDetail = { error?: string; message?: string; dependencies?: Record<string, number | string> };

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

function formatFileSize(bytes?: number | null) {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString();
}

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
  const [deleteNameConfirmation, setDeleteNameConfirmation] = useState('');
  const [logoUploadingId, setLogoUploadingId] = useState<string | null>(null);
  const [logoErrors, setLogoErrors] = useState<Record<string, string>>({});

  const user = getAuthUser();
  const isLeagueAdmin = user?.role_name === 'LEAGUE_ADMIN';
  const notifyOrganizationsChanged = () => window.dispatchEvent(new Event('organizations:changed'));
  const notifyAdminDataChanged = () => window.dispatchEvent(new Event('admin:data-changed'));

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
      setMessage(editingId ? 'Updated successfully' : 'Created successfully'); setType('ok'); setForm({ is_active: true }); setEditingId(null); notifyOrganizationsChanged(); load();
    } catch (e: any) { setMessage(e?.message || 'Save failed'); setType('err'); }
    finally { setSaving(false); }
  };

  const openDeleteModal = (item: Organization) => {
    setDeleteTarget(item); setCascadeConfirmed(false); setDeleteNameConfirmation(''); setDeleteError('');
  };

  const closeDeleteModal = () => { setDeleteTarget(null); setDeleteError(''); setCascadeConfirmed(false); setDeleteNameConfirmation(''); };

  const deactivateOrganization = async () => {
    if (!deleteTarget) return;
    setDeleteError('');
    try {
      await apiFetch(`/organizations/${deleteTarget.id}`, { method: 'PUT', body: JSON.stringify({ ...deleteTarget, is_active: false }) }, getToken());
      setMessage(`${deleteTarget.name} marked inactive`); setType('ok'); closeDeleteModal(); notifyOrganizationsChanged(); load();
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
      setMessage('Organization and related records deleted.'); setType('ok'); closeDeleteModal(); notifyOrganizationsChanged(); notifyAdminDataChanged(); load();
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : undefined;
      const detailObject = (apiError?.detail && typeof apiError.detail === 'object' ? apiError.detail : apiError?.details) as DeleteDependencyErrorDetail | undefined;
      const fallback = 'Unable to delete organization.';
      const serverMessage = detailObject?.message || apiError?.message || fallback;
      setDeleteError(serverMessage);
      setMessage(serverMessage);
      setType('err');
    }
  };

  const validateLogoFile = (organizationId: string, file?: File) => {
    if (!file) return false;
    const isPng = file.type === 'image/png' && file.name.toLowerCase().endsWith('.png');
    if (!isPng) {
      setLogoErrors((current) => ({ ...current, [organizationId]: 'Only PNG logo files are accepted.' }));
      return false;
    }
    if (file.size > MAX_LOGO_BYTES) {
      setLogoErrors((current) => ({ ...current, [organizationId]: 'Logo file must be 2 MB or smaller.' }));
      return false;
    }
    setLogoErrors((current) => ({ ...current, [organizationId]: '' }));
    return true;
  };

  const uploadLogo = async (organization: Organization, file?: File) => {
    if (!validateLogoFile(organization.id, file)) return;
    const data = new FormData();
    data.append('file', file as File);
    setLogoUploadingId(organization.id);
    try {
      await apiFetch(`/organizations/${organization.id}/logo`, { method: 'POST', body: data }, getToken());
      setMessage(`${organization.name} logo uploaded.`); setType('ok'); load();
    } catch (e: any) { setLogoErrors((current) => ({ ...current, [organization.id]: e?.message || 'Logo upload failed' })); setMessage(e?.message || 'Logo upload failed'); setType('err'); }
    finally { setLogoUploadingId(null); }
  };

  const onLogoFileChange = (organization: Organization, event: ChangeEvent<HTMLInputElement>) => {
    uploadLogo(organization, event.target.files?.[0]);
    event.target.value = '';
  };

  const removeLogo = async (organization: Organization) => {
    setLogoUploadingId(organization.id);
    try {
      await apiFetch(`/organizations/${organization.id}/logo`, { method: 'DELETE' }, getToken());
      setLogoErrors((current) => ({ ...current, [organization.id]: '' }));
      setMessage(`${organization.name} logo removed.`); setType('ok'); load();
    } catch (e: any) { setMessage(e?.message || 'Logo removal failed'); setType('err'); }
    finally { setLogoUploadingId(null); }
  };

  const requiresCascadeConfirmation = isLeagueAdmin;
  const deleteNameMatches = deleteNameConfirmation.trim() === (deleteTarget?.name || '');
  const deleteButtonDisabled = requiresCascadeConfirmation && (!cascadeConfirmed || !deleteNameMatches);

  return <div className='space-y-4'>
    <Toast message={message} type={type} />
    <h1 className='text-2xl font-bold'>{isLeagueAdmin ? 'Organizations' : 'My Community'}</h1>
    <div className='flex gap-2'><input className='w-full max-w-sm rounded border p-2' value={query} onChange={(e) => setQuery(e.target.value)} placeholder='Search...' /><button className='rounded bg-slate-700 px-3 py-2 text-white' onClick={load}>Filter</button></div>
    <div className='grid gap-3 rounded border p-4 md:grid-cols-2'>
      <FormField label='Name' type='text' value={form.name ?? ''} onChange={(v) => setForm({ ...form, name: String(v) })} />
      {isLeagueAdmin && <FormField label='Active' type='checkbox' value={form.is_active ?? true} onChange={(v) => setForm({ ...form, is_active: Boolean(v) })} />}
      <div className='md:col-span-2 flex gap-2'><button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:opacity-50' onClick={save} disabled={saving || (!isLeagueAdmin && !editingId)}>{saving ? 'Saving…' : editingId ? 'Update' : 'Create'}</button>{editingId && <button className='rounded border px-4 py-2' onClick={() => { setForm({ is_active: true }); setEditingId(null); }}>Cancel</button>}</div>
    </div>

    <section className='rounded border border-sky-200 bg-sky-50 p-4 text-sm text-slate-800'>
      <h2 className='text-lg font-semibold text-slate-900'>Community Logo</h2>
      <p className='mt-1'>Upload a PNG version of your community logo. This logo will be used on schedules, tournament brackets, and downloadable bracket/schedule documents.</p>
      <div className='mt-3 font-medium'>Logo standard:</div>
      <ul className='mt-1 list-disc space-y-0.5 pl-5'>
        <li>File type: PNG only</li>
        <li>Recommended background: transparent</li>
        <li>Recommended shape: square or close to square</li>
        <li>Minimum size: 500 × 500 pixels</li>
        <li>Recommended size: 1000 × 1000 pixels</li>
        <li>Maximum file size: 2 MB</li>
        <li>Avoid blurry screenshots, stretched images, or logos with large empty margins.</li>
      </ul>
      <p className='mt-2 text-xs font-medium text-slate-600'>PNG with a transparent background is recommended for best appearance.</p>
    </section>

    {loading ? <p>Loading records...</p> : <div className='grid gap-4'>{items.map((item) => <CommunityLogoCard key={item.id} organization={item} isBusy={logoUploadingId === item.id} error={logoErrors[item.id]} onFileChange={onLogoFileChange} onRemove={removeLogo} onEdit={() => { setForm(item); setEditingId(item.id); }} onDelete={isLeagueAdmin ? () => openDeleteModal(item) : undefined} />)}</div>}

    {deleteTarget && <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4'><div className='w-full max-w-lg rounded bg-white p-5 shadow-lg'>
      <h2 className='text-lg font-semibold'>Organization Actions</h2>
      <p className='mt-2 text-sm text-slate-700'>You are deleting <span className='font-semibold'>{deleteTarget.name}</span>.</p>
      {deleteError && <p className='mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700'>{deleteError}</p>}
      <p className='mt-3 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800'>This will permanently delete the organization and all related setup, teams, host locations, availability, generated slots, and scheduled games. This cannot be undone.</p>
      {requiresCascadeConfirmation && <div className='mt-3 space-y-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm'><label className='flex items-start gap-2'><input type='checkbox' className='mt-1' checked={cascadeConfirmed} onChange={(e) => setCascadeConfirmed(e.target.checked)} /><span>I understand this will permanently delete this organization and all related setup data.</span></label><div><label className='font-medium text-rose-900'>Type <span className='font-bold'>{deleteTarget.name}</span> to confirm.</label><input className='mt-1 w-full rounded border border-rose-300 bg-white p-2' value={deleteNameConfirmation} onChange={(e) => setDeleteNameConfirmation(e.target.value)} placeholder={deleteTarget.name} /></div><p className='text-rose-700'>This action cannot be undone.</p></div>}
      <div className='mt-4 flex flex-wrap justify-end gap-2'><button className='rounded border px-3 py-2' onClick={closeDeleteModal}>Cancel</button><button className='rounded border border-amber-500 px-3 py-2 text-amber-700' onClick={deactivateOrganization}>Mark Inactive</button><button className={`rounded px-3 py-2 text-white ${deleteButtonDisabled ? 'bg-slate-400' : 'bg-rose-700 hover:bg-rose-800'}`} disabled={deleteButtonDisabled} onClick={confirmDelete}>Delete Organization</button></div>
    </div></div>}
  </div>;
}

function CommunityLogoCard({ organization, isBusy, error, onFileChange, onRemove, onEdit, onDelete }: {
  organization: Organization;
  isBusy: boolean;
  error?: string;
  onFileChange: (organization: Organization, event: ChangeEvent<HTMLInputElement>) => void;
  onRemove: (organization: Organization) => void;
  onEdit: () => void;
  onDelete?: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const hasLogo = Boolean(organization.logo_url);
  const dimensions = organization.logo_width && organization.logo_height ? `${organization.logo_width} × ${organization.logo_height}px` : '';
  const uploadedAt = formatDate(organization.logo_uploaded_at);

  return <article className='rounded border bg-white p-4 shadow-sm'>
    <div className='flex flex-col gap-4 md:flex-row md:items-start md:justify-between'>
      <div className='flex min-w-0 gap-4'>
        <CommunityLogo src={organization.logo_url} name={organization.name} size={96} className='rounded-xl' />
        <div className='min-w-0'>
          <h3 className='text-lg font-semibold text-slate-900'>{organization.name}</h3>
          <p className='text-sm text-slate-500'>{organization.is_active ? 'Active community' : 'Inactive community'}</p>
          <div className='mt-3 text-sm text-slate-700'>
            {hasLogo ? <>
              <p className='font-medium text-slate-900'>Current logo preview</p>
              <dl className='mt-1 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2'>
                {organization.logo_filename && <><dt className='font-medium text-slate-500'>File name</dt><dd className='truncate'>{organization.logo_filename}</dd></>}
                {dimensions && <><dt className='font-medium text-slate-500'>Dimensions</dt><dd>{dimensions}</dd></>}
                {organization.logo_content_type && <><dt className='font-medium text-slate-500'>File type</dt><dd>{organization.logo_content_type}</dd></>}
                {organization.logo_file_size && <><dt className='font-medium text-slate-500'>File size</dt><dd>{formatFileSize(organization.logo_file_size)}</dd></>}
                {uploadedAt && <><dt className='font-medium text-slate-500'>Upload date</dt><dd>{uploadedAt}</dd></>}
              </dl>
            </> : <p>No logo uploaded. The placeholder initials shown here will be used until a PNG logo is uploaded.</p>}
          </div>
        </div>
      </div>
      <div className='flex flex-col gap-2 md:items-end'>
        <input ref={fileInputRef} className='sr-only' type='file' accept='image/png,.png' aria-label={`${hasLogo ? 'Replace' : 'Upload'} PNG Logo for ${organization.name}`} disabled={isBusy} onChange={(event) => onFileChange(organization, event)} />
        <button className='rounded bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50' disabled={isBusy} onClick={() => fileInputRef.current?.click()}>{isBusy ? 'Uploading…' : hasLogo ? 'Replace Logo' : 'Upload PNG Logo'}</button>
        {hasLogo && <button className='rounded border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-50' disabled={isBusy} onClick={() => onRemove(organization)}>Remove Logo</button>}
        <div className='flex gap-2 pt-2'>
          <button className='text-sm text-blue-700' onClick={onEdit}>Edit</button>
          {onDelete && <button className='text-sm text-rose-700' onClick={onDelete}>Delete</button>}
        </div>
        {error && <p className='max-w-xs rounded border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700'>{error}</p>}
      </div>
    </div>
  </article>;
}
