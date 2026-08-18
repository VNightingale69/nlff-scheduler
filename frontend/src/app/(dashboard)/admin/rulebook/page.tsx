'use client';

import { FormEvent, useEffect, useState } from 'react';
import { API_URL, apiFetch } from '@/lib/api';
import { useAuthSession } from '@/components/AuthGate';

type LeagueDocument = {
  original_filename: string; file_size_bytes: number; uploaded_at: string;
  uploaded_by_name?: string | null; uploaded_by_email?: string | null;
  view_url: string; download_url: string; file_url?: string | null;
  file_available?: boolean; storage_error?: string | null;
};

const formatBytes = (bytes: number) => {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};
const rulebookUrl = (path?: string | null) => {
  if (!path) return '#';
  if (/^https?:\/\//.test(path)) return path;
  const normalizedPath = path.startsWith('/api/') ? path.slice(4) : path;
  return `${API_URL}${normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`}`;
};

type DocumentSectionProps = {
  title: string; document: LeagueDocument | null; endpoint: string; token?: string;
  emptyText: string; helpText: string; replaceLabel: string;
  onUploaded: (document: LeagueDocument, message: string) => void;
  onError: (message: string) => void; canManage: boolean;
};

function DocumentSection({ title, document, endpoint, token, emptyText, helpText, replaceLabel, onUploaded, onError, canManage }: DocumentSectionProps) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const upload = async (event: FormEvent) => {
    event.preventDefault(); onError('');
    if (!file) return onError('Please choose a PDF file to upload.');
    if (file.type !== 'application/pdf' || !file.name.toLowerCase().endsWith('.pdf')) return onError('Only PDF files are allowed.');
    if (file.size > 25 * 1024 * 1024) return onError('The selected file exceeds the 25 MB maximum file size.');
    setUploading(true);
    try {
      const body = new FormData(); body.append('file', file);
      const response = await fetch(`${API_URL}${endpoint}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail || 'Upload failed.');
      setFile(null);
      onUploaded(payload, `${title} ${document ? 'replaced' : 'uploaded'} successfully.`);
    } catch (error: any) { onError(error?.message || 'Upload failed. Please try again.'); }
    finally { setUploading(false); }
  };
  return <section className='rounded border bg-white p-4 shadow-sm'>
    <h2 className='text-lg font-semibold'>{title}</h2>
    {document ? <>
      <dl className='mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4'>
        <div><dt className='font-medium text-slate-500'>Original filename</dt><dd>{document.original_filename}</dd></div>
        <div><dt className='font-medium text-slate-500'>Uploaded date</dt><dd>{new Date(document.uploaded_at).toLocaleString()}</dd></div>
        <div><dt className='font-medium text-slate-500'>Uploaded by</dt><dd>{document.uploaded_by_name || document.uploaded_by_email || 'Unknown'}</dd></div>
        <div><dt className='font-medium text-slate-500'>File size</dt><dd>{formatBytes(document.file_size_bytes)}</dd></div>
      </dl>
      {document.file_available === false && <p className='mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900'>{document.storage_error}</p>}
      {document.file_available !== false && <div className='mt-4 flex gap-2'>
        <a className='rounded bg-slate-800 px-3 py-2 text-white' href={rulebookUrl(document.view_url || document.file_url)} target='_blank' rel='noreferrer'>View</a>
        <a className='rounded border px-3 py-2' href={rulebookUrl(document.download_url)}>Download</a>
      </div>}
    </> : <div className='mt-3 text-sm'><p>{emptyText}</p><p className='mt-1 text-slate-600'>{helpText}</p></div>}
    {canManage && <form className='mt-5 border-t pt-4' onSubmit={upload}>
      <h3 className='font-semibold'>{replaceLabel}</h3>
      <p className='mb-3 text-sm text-slate-600'>Only PDF files are allowed. Maximum file size is 25 MB.</p>
      <input key={document?.uploaded_at || 'empty'} type='file' accept='application/pdf,.pdf' onChange={(e) => setFile(e.target.files?.[0] || null)} />
      <div className='mt-4'><button className='rounded bg-blue-700 px-3 py-2 text-white disabled:opacity-60' disabled={uploading}>{uploading ? 'Uploading...' : document ? 'Upload/Replace PDF' : `Upload ${title}`}</button></div>
    </form>}
  </section>;
}

export default function RulebookManagementPage() {
  const [rulebook, setRulebook] = useState<LeagueDocument | null>(null);
  const [infographic, setInfographic] = useState<LeagueDocument | null>(null);
  const [loading, setLoading] = useState(true); const [message, setMessage] = useState(''); const [error, setError] = useState('');
  const { accessToken: token, currentUser: user } = useAuthSession();
  const isLeagueAdmin = user?.role_name === 'LEAGUE_ADMIN';
  useEffect(() => { Promise.all([
    apiFetch('/rulebook', {}, token).catch((e) => e?.status === 404 ? null : Promise.reject(e)),
    apiFetch('/rule-infographic', {}, token).catch((e) => e?.status === 404 ? null : Promise.reject(e)),
  ]).then(([rules, graphic]) => { setRulebook(rules); setInfographic(graphic); }).catch((e) => setError(e?.message || 'Unable to load league documents.')).finally(() => setLoading(false)); }, [token]);
  return <div className='space-y-4'>
    <div><h1 className='text-2xl font-bold'>Rulebook Management</h1><p className='text-sm text-slate-600'>Manage league rules and supporting documents.</p></div>
    {message && <div className='rounded border border-green-200 bg-green-50 p-3 text-sm text-green-800'>{message}</div>}
    {error && <div className='rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800'>{error}</div>}
    {loading ? <div className='rounded border p-4'>Loading league documents...</div> : <>
      <DocumentSection title='Official Rulebook' document={rulebook} endpoint='/admin/rulebook/upload' token={token} emptyText='No rulebook has been uploaded yet.' helpText='Upload the official league rules.' replaceLabel='Replace Rulebook PDF' onError={setError} canManage={isLeagueAdmin} onUploaded={(d,m) => { setRulebook(d); setError(''); setMessage(m); }} />
      <DocumentSection title='Rule Infographic' document={infographic} endpoint='/admin/rule-infographic/upload' token={token} emptyText='No Rule Infographic has been uploaded.' helpText='Upload a PDF to make the quick-reference rules available to the public.' replaceLabel='Upload/Replace Rule Infographic PDF' onError={setError} canManage={isLeagueAdmin} onUploaded={(d,m) => { setInfographic(d); setError(''); setMessage(m); }} />
    </>}
  </div>;
}
