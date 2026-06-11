'use client';

import { FormEvent, useEffect, useState } from 'react';
import { API_URL, apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';

type Rulebook = {
  original_filename: string;
  file_size_bytes: number;
  uploaded_at: string;
  uploaded_by_name?: string | null;
  uploaded_by_email?: string | null;
  view_url: string;
  download_url: string;
  file_url?: string | null;
  file_available?: boolean;
  storage_error?: string | null;
};


type StorageDiagnostics = {
  rulebook_storage_writable?: boolean;
  rulebook_active_file_exists?: boolean;
  rulebook_active_metadata_exists?: boolean;
  rulebook_storage_dir?: string;
  upload_storage_dir?: string;
  upload_storage_dir_configured?: boolean;
};

const formatBytes = (bytes: number) => {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
};

const noRulebookMessage = 'No rulebook has been uploaded yet.';

const rulebookUrl = (path?: string | null) => {
  if (!path) return '#';
  if (/^https?:\/\//.test(path)) return path;
  const normalizedPath = path.startsWith('/api/') ? path.slice(4) : path;
  return `${API_URL}${normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`}`;
};

export default function RulebookManagementPage() {
  const [rulebook, setRulebook] = useState<Rulebook | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [storageDiagnostics, setStorageDiagnostics] = useState<StorageDiagnostics | null>(null);
  const user = getAuthUser();
  const isLeagueAdmin = user?.role_name === 'LEAGUE_ADMIN';

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await apiFetch('/rulebook', {}, getToken());
      setRulebook(data);
      if (data?.file_available === false) {
        try {
          setStorageDiagnostics(await apiFetch('/admin/storage-diagnostics', {}, getToken()));
        } catch {
          setStorageDiagnostics(null);
        }
      } else {
        setStorageDiagnostics(null);
      }
    } catch (err: any) {
      setRulebook(null);
      setStorageDiagnostics(null);
      if (err?.status === 404) setMessage(noRulebookMessage);
      else setError(err?.message || 'Unable to load the rulebook.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const upload = async (event: FormEvent) => {
    event.preventDefault();
    setMessage('');
    setError('');

    if (!selectedFile) {
      setError('Please choose a PDF file to upload.');
      return;
    }
    if (selectedFile.type !== 'application/pdf' || !selectedFile.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are allowed.');
      return;
    }

    setUploading(true);
    const body = new FormData();
    body.append('file', selectedFile);

    try {
      const response = await fetch(`${API_URL}/admin/rulebook/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail || 'Upload failed.');
      setRulebook(payload);
      setStorageDiagnostics(null);
      setSelectedFile(null);
      setMessage('Rulebook uploaded successfully.');
    } catch (err: any) {
      setError(err?.message || 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className='space-y-4'>
      <div>
        <h1 className='text-2xl font-bold'>{isLeagueAdmin ? 'Rulebook Management' : 'Rulebook'}</h1>
        <p className='text-sm text-slate-600'>{isLeagueAdmin ? 'Upload or replace the active league rulebook PDF.' : 'View and download the current league rulebook.'}</p>
      </div>

      {message && <div className='rounded border border-green-200 bg-green-50 p-3 text-sm text-green-800'>{message}</div>}
      {error && <div className='rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800'>{error}</div>}
      {loading && <div className='rounded border p-4'>Loading rulebook...</div>}

      {!loading && rulebook && (
        <section className='rounded border bg-white p-4 shadow-sm'>
          <h2 className='text-lg font-semibold'>Current rulebook</h2>
          <dl className='mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4'>
            <div><dt className='font-medium text-slate-500'>Original filename</dt><dd>{rulebook.original_filename}</dd></div>
            <div><dt className='font-medium text-slate-500'>Uploaded date</dt><dd>{new Date(rulebook.uploaded_at).toLocaleString()}</dd></div>
            <div><dt className='font-medium text-slate-500'>Uploaded by</dt><dd>{rulebook.uploaded_by_name || rulebook.uploaded_by_email || 'Unknown'}</dd></div>
            <div><dt className='font-medium text-slate-500'>File size</dt><dd>{formatBytes(rulebook.file_size_bytes)}</dd></div>
          </dl>
          {rulebook.file_available === false && (
            <div className='mt-4 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900'>
              <p>{rulebook.storage_error || 'Rulebook metadata exists, but the file is missing from configured storage. Confirm that UPLOAD_STORAGE_DIR is backed by persistent storage, then re-upload the rulebook.'}</p>
              {storageDiagnostics && (
                <dl className='mt-3 grid gap-2 sm:grid-cols-3'>
                  <div><dt className='font-medium'>Configured upload directory</dt><dd className='break-all'>{storageDiagnostics.upload_storage_dir || storageDiagnostics.rulebook_storage_dir || 'Not configured'}</dd></div>
                  <div><dt className='font-medium'>Directory writable</dt><dd>{storageDiagnostics.rulebook_storage_writable ? 'Yes' : 'No'}</dd></div>
                  <div><dt className='font-medium'>Active file exists</dt><dd>{storageDiagnostics.rulebook_active_file_exists ? 'Yes' : 'No'}</dd></div>
                </dl>
              )}
            </div>
          )}
          <div className='mt-4 flex flex-wrap gap-2'>
            {rulebook.file_available === false ? (
              <>
                <span className='rounded bg-slate-300 px-3 py-2 text-slate-600'>View unavailable</span>
                <span className='rounded border px-3 py-2 text-slate-500'>Download unavailable</span>
              </>
            ) : (
              <>
                <a className='rounded bg-slate-800 px-3 py-2 text-white' href={rulebookUrl(rulebook.view_url || rulebook.file_url)} target='_blank' rel='noreferrer'>View</a>
                <a className='rounded border px-3 py-2' href={rulebookUrl(rulebook.download_url)}>Download</a>
              </>
            )}
          </div>
        </section>
      )}

      {!loading && !rulebook && !message && <div className='rounded border p-4'>{noRulebookMessage}</div>}

      {isLeagueAdmin && (
        <form className='rounded border bg-white p-4 shadow-sm' onSubmit={upload}>
          <h2 className='text-lg font-semibold'>{rulebook ? 'Replace PDF' : 'Upload PDF'}</h2>
          <p className='mb-3 text-sm text-slate-600'>Only PDF files are allowed. Maximum file size is 25 MB.</p>
          <input type='file' accept='application/pdf,.pdf' onChange={(e) => setSelectedFile(e.target.files?.[0] || null)} />
          <div className='mt-4'>
            <button className='rounded bg-blue-700 px-3 py-2 text-white disabled:opacity-60' type='submit' disabled={uploading}>{uploading ? 'Uploading...' : rulebook ? 'Upload/Replace PDF' : 'Upload PDF'}</button>
          </div>
        </form>
      )}
    </div>
  );
}
