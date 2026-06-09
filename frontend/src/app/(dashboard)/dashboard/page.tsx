'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { APP_NAME, APP_SUBTITLE } from '@/config/branding';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';

export default function DashboardPage() {
  const [missingCount, setMissingCount] = useState(0);
  const [linkTarget, setLinkTarget] = useState('/admin/score-entry');
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const user = getAuthUser();
    const token = getToken() || undefined;
    if (!token || user?.role_name !== 'COMMUNITY_ADMIN') return;
    apiFetch('/scores/missing-summary', {}, token)
      .then((data) => {
        setMissingCount(data?.missing_count || 0);
        setLinkTarget(data?.link_target || '/admin/score-entry');
      })
      .catch(() => undefined);
  }, []);

  return <div className='space-y-4'>
    {missingCount > 0 && !dismissed && <div className='rounded border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <p className='font-medium'>You have {missingCount} missing game score(s) that need to be submitted.</p>
        <div className='flex gap-2'>
          <Link className='rounded bg-amber-700 px-3 py-2 text-white' href={linkTarget}>Go to Score Management</Link>
          <button className='rounded border border-amber-400 px-3 py-2' onClick={() => setDismissed(true)}>Dismiss</button>
        </div>
      </div>
    </div>}
    <div className='rounded border bg-white p-6'><h1 className='text-2xl font-bold'>{APP_NAME}</h1><p className='mt-1 text-sm font-medium text-slate-700'>{APP_SUBTITLE}</p><p className='mt-3 text-slate-600'>Welcome to the Community Flag Scheduler administrative frontend. Use the sidebar to manage organizations, divisions, host locations, fields, teams, and hosting availability.</p></div>
  </div>;
}
