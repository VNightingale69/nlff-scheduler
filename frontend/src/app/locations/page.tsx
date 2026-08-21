'use client';

import { useEffect, useMemo, useState } from 'react';
import PublicLayout from '@/components/public/PublicLayout';
import { API_URL } from '@/lib/api';

type HostingLocation = {
  id: string;
  name: string;
  community: string;
  address_line_1?: string | null;
  address_line_2?: string | null;
  city?: string | null;
  state?: string | null;
  postal_code?: string | null;
  public_notes?: string | null;
};

const clean = (value?: string | null) => value?.trim() || '';
const hasCompleteAddress = (location: HostingLocation) => Boolean(
  clean(location.address_line_1) && clean(location.city) && clean(location.state) && clean(location.postal_code),
);
const addressQuery = (location: HostingLocation) => [
  location.address_line_1, location.address_line_2, location.city, location.state, location.postal_code,
].map(clean).filter(Boolean).join(', ');

export default function HostingLocationsPage() {
  const [locations, setLocations] = useState<HostingLocation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetch(`${API_URL}/public/hosting-locations`)
      .then(async response => {
        if (!response.ok) throw new Error('Locations could not be loaded.');
        setLocations(await response.json());
      })
      .catch(() => setError('Hosting locations are temporarily unavailable. Please try again later.'))
      .finally(() => setLoading(false));
  }, []);

  const groups = useMemo(() => locations.reduce<Record<string, HostingLocation[]>>((result, location) => {
    (result[location.community] ||= []).push(location);
    return result;
  }, {}), [locations]);

  return <PublicLayout>
    <main className='mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-10 lg:px-8'>
      <header className='mb-8'>
        <p className='text-sm font-bold uppercase tracking-[0.18em] text-emerald-700'>Plan your visit</p>
        <h1 className='mt-2 text-3xl font-black tracking-tight text-slate-950 sm:text-4xl'>Hosting Locations</h1>
        <p className='mt-3 max-w-2xl text-base text-slate-600'>Addresses and directions for Community Flag Football hosting sites.</p>
      </header>
      {loading && <p role='status' className='rounded-xl border bg-white p-5 text-slate-600'>Loading hosting locations…</p>}
      {error && <p role='alert' className='rounded-xl border border-rose-200 bg-rose-50 p-5 text-rose-800'>{error}</p>}
      {!loading && !error && locations.length === 0 && <p className='rounded-xl border border-dashed p-6 text-slate-600'>No active hosting locations are currently available.</p>}
      <div className='space-y-10'>
        {Object.entries(groups).map(([community, communityLocations]) => <section key={community} aria-labelledby={`community-${communityLocations[0].id}`}>
          <h2 id={`community-${communityLocations[0].id}`} className='mb-4 border-b-2 border-emerald-700 pb-2 text-2xl font-extrabold text-slate-900'>{community}</h2>
          <div className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3'>
            {communityLocations.map(location => {
              const complete = hasCompleteAddress(location);
              const cityLine = [clean(location.city), clean(location.state)].filter(Boolean).join(', ') + (clean(location.postal_code) ? ` ${clean(location.postal_code)}` : '');
              return <article id={`location-${location.id}`} key={location.id} className='scroll-mt-24 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm'>
                <h3 className='text-xl font-extrabold leading-snug text-slate-950'>{location.name}</h3>
                <p className='mt-1 text-sm font-semibold text-emerald-800'>Community: {location.community}</p>
                {complete ? <address className='mt-4 not-italic leading-7 text-slate-700'>
                  <span className='block break-words'>{clean(location.address_line_1)}</span>
                  {clean(location.address_line_2) && <span className='block break-words'>{clean(location.address_line_2)}</span>}
                  <span className='block break-words'>{cityLine}</span>
                </address> : <p className='mt-4 font-medium text-slate-500'>Address not yet available</p>}
                {clean(location.public_notes) && <p className='mt-4 whitespace-pre-line text-sm leading-6 text-slate-600'>{clean(location.public_notes)}</p>}
                {complete && <a className='mt-5 inline-flex min-h-11 w-full items-center justify-center rounded-lg bg-emerald-700 px-4 py-3 text-center font-bold text-white hover:bg-emerald-800 focus:outline-none focus-visible:ring-4 focus-visible:ring-emerald-300' href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addressQuery(location))}`} target='_blank' rel='noopener noreferrer' aria-label={`Get directions to ${location.name}`}>Get Directions<span className='sr-only'> (opens in a new tab)</span></a>}
              </article>;
            })}
          </div>
        </section>)}
      </div>
    </main>
  </PublicLayout>;
}
