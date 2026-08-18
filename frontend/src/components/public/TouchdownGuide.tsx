'use client';

import Link from 'next/link';
import { useId, useState } from 'react';
import { fieldTypeLabel, SCORING_GUIDE_SECTIONS } from '@/lib/divisionScoring';

const tones = {
  small: 'border-emerald-300 bg-emerald-50 text-emerald-950',
  medium: 'border-sky-300 bg-sky-50 text-sky-950',
  large: 'border-amber-300 bg-amber-50 text-amber-950',
};

function GuideContent({ headingIdPrefix }: { headingIdPrefix: string }) {
  return <div className='space-y-4'>
    <div><h3 className='text-lg font-bold text-slate-900'>How Scoring Works</h3><p className='mt-1 text-sm leading-5 text-slate-600'>Scoring varies by division and field size.<br />See your division below.</p></div>
    {SCORING_GUIDE_SECTIONS.map(section => { const headingId = `${headingIdPrefix}-${section.fieldType}-field-heading`; return <section key={section.fieldType} className={`rounded-lg border-l-4 p-3 ${tones[section.fieldType]}`} aria-labelledby={headingId}>
      <h4 id={headingId} className='text-xs font-extrabold uppercase tracking-wider'><span aria-hidden='true'>● </span>{fieldTypeLabel(section.fieldType)} Divisions</h4>
      <p className='mt-2 font-bold'>Touchdown = {section.touchdownPoints} {section.touchdownPoints === 1 ? 'point' : 'points'}</p>
      {section.extraPointRule === 'none' ? <p className='mt-1 rounded bg-emerald-900 px-2 py-1 text-xs font-extrabold uppercase tracking-wide text-white'>No extra-point attempts</p> : <p className='mt-1 text-sm font-semibold'>Optional 1-point or 2-point conversion</p>}
      <ul className='mt-2 space-y-0.5 text-sm'>{section.divisions.map(division => <li key={division}>• {division}</li>)}</ul>
    </section>; })}
    <p className='border-t border-slate-200 pt-3 text-sm text-slate-600'>Questions? <Link href='/rulebook' className='font-semibold text-emerald-800 underline decoration-emerald-300 underline-offset-2 hover:text-emerald-950'>View the Rules</Link> for more details.</p>
  </div>;
}

export default function TouchdownGuide({ variant }: { variant: 'desktop' | 'mobile' }) {
  const [expanded, setExpanded] = useState(false);
  const reactId = useId().replace(/:/g, '');
  const contentId = `touchdown-guide-content-${reactId}`;

  if (variant === 'desktop') return <aside aria-label='Touchdown Guide' data-testid='desktop-touchdown-guide' className='hidden rounded-xl border border-slate-200 bg-white shadow-sm min-[900px]:block'>
    <h2 className='rounded-t-xl border-b border-slate-200 bg-slate-900 px-5 py-4 text-sm font-extrabold uppercase tracking-widest text-white'><span aria-hidden='true'>🏈 </span>Touchdown Guide</h2>
    <div className='p-5'><GuideContent headingIdPrefix={`desktop-${reactId}`} /></div>
  </aside>;

  return <section aria-label='Touchdown Guide' data-testid='mobile-touchdown-guide' className='min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm min-[900px]:hidden'>
    <h2>
      <button type='button' aria-expanded={expanded} aria-controls={contentId} onClick={() => setExpanded(current => !current)} className='flex w-full items-center justify-between rounded-xl bg-slate-900 px-4 py-3 text-left text-sm font-extrabold uppercase tracking-wider text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2'>
        <span><span aria-hidden='true'>🏈 </span>Touchdown Guide</span>
        <span aria-hidden='true'>{expanded ? '▲' : '▼'}</span>
      </button>
    </h2>
    <div id={contentId} hidden={!expanded} className='border-t border-slate-200 p-4'><GuideContent headingIdPrefix={`mobile-${reactId}`} /></div>
  </section>;
}
