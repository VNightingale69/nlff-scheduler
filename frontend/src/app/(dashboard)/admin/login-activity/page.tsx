'use client';

import { FormEvent, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

type LoginAuditLog = {
  id: string;
  email_attempted: string;
  user_role?: string | null;
  community_name?: string | null;
  success: boolean;
  failure_reason?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  login_at: string;
};

const resultOptions = [
  { label: 'All Results', value: '' },
  { label: 'Successful', value: 'true' },
  { label: 'Failed', value: 'false' },
];

function formatLoginTime(value: string) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function LoginActivityPage() {
  const [items, setItems] = useState<LoginAuditLog[]>([]);
  const [message, setMessage] = useState('');
  const [filters, setFilters] = useState({ email: '', role: '', community_id: '', success: '', date_from: '', date_to: '' });

  const load = async () => {
    try {
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
      const query = params.toString();
      const data = await apiFetch(`/admin/login-audit${query ? `?${query}` : ''}`, {}, getToken() || undefined);
      setItems(Array.isArray(data) ? data : []);
      setMessage('');
    } catch (error: any) {
      setMessage(error?.message || 'Unable to load login activity.');
    }
  };

  useEffect(() => { load(); }, []);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    load();
  };

  return <div className='space-y-4'>
    <div>
      <h1 className='text-2xl font-bold'>Login Activity</h1>
      <p className='text-sm text-slate-600'>Scheduling Administrator security log for successful and failed login attempts. Newest attempts appear first.</p>
    </div>

    {message && <div className='rounded border bg-red-50 p-3 text-sm text-red-700'>{message}</div>}

    <form className='grid gap-3 rounded border bg-white p-4 md:grid-cols-6' onSubmit={applyFilters}>
      <label className='text-sm'>User Email<input className='mt-1 w-full rounded border p-2' value={filters.email} onChange={(event) => setFilters({ ...filters, email: event.target.value })} placeholder='user@example.com' /></label>
      <label className='text-sm'>Role<input className='mt-1 w-full rounded border p-2' value={filters.role} onChange={(event) => setFilters({ ...filters, role: event.target.value })} placeholder='SCHEDULING_ADMIN' /></label>
      <label className='text-sm'>Community ID<input className='mt-1 w-full rounded border p-2' value={filters.community_id} onChange={(event) => setFilters({ ...filters, community_id: event.target.value })} /></label>
      <label className='text-sm'>Result<select className='mt-1 w-full rounded border p-2' value={filters.success} onChange={(event) => setFilters({ ...filters, success: event.target.value })}>{resultOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
      <label className='text-sm'>Date From<input className='mt-1 w-full rounded border p-2' type='date' value={filters.date_from} onChange={(event) => setFilters({ ...filters, date_from: event.target.value })} /></label>
      <label className='text-sm'>Date To<input className='mt-1 w-full rounded border p-2' type='date' value={filters.date_to} onChange={(event) => setFilters({ ...filters, date_to: event.target.value })} /></label>
      <div className='md:col-span-6'><button className='rounded bg-slate-800 px-3 py-2 text-sm text-white' type='submit'>Apply Filters</button></div>
    </form>

    <div className='overflow-x-auto rounded border bg-white'>
      <table className='min-w-full text-sm'>
        <thead className='bg-slate-100 text-left'><tr>{['Login Time', 'User Email', 'User Role', 'Community', 'Result', 'Failure Reason', 'IP Address', 'Browser / User Agent'].map((header) => <th key={header} className='p-2'>{header}</th>)}</tr></thead>
        <tbody>{items.map((item) => <tr key={item.id} className='border-t align-top'>
          <td className='whitespace-nowrap p-2'>{formatLoginTime(item.login_at)}</td>
          <td className='p-2'>{item.email_attempted}</td>
          <td className='p-2'>{item.user_role || '—'}</td>
          <td className='p-2'>{item.community_name || '—'}</td>
          <td className='p-2'><span className={item.success ? 'font-semibold text-green-700' : 'font-semibold text-red-700'}>{item.success ? 'Success' : 'Failed'}</span></td>
          <td className='p-2'>{item.failure_reason || '—'}</td>
          <td className='p-2'>{item.ip_address || '—'}</td>
          <td className='max-w-xl break-words p-2'>{item.user_agent || '—'}</td>
        </tr>)}</tbody>
      </table>
      {items.length === 0 && <div className='p-4 text-sm text-slate-500'>No login activity found.</div>}
    </div>
  </div>;
}
