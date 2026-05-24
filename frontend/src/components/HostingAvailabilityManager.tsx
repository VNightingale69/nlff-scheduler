'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';
import Toast from './Toast';
import { useSearchParams } from 'next/navigation';

const HOSTING_DATES = [
  { date: '2026-09-06', label: 'Saturday, September 6' },
  { date: '2026-09-13', label: 'Saturday, September 13' },
  { date: '2026-09-20', label: 'Saturday, September 20' },
  { date: '2026-09-27', label: 'Saturday, September 27' },
  { date: '2026-10-04', label: 'Saturday, October 4' },
  { date: '2026-10-11', label: 'Saturday, October 11' },
  { date: '2026-10-18', label: 'Saturday, October 18 — Playoffs' },
  { date: '2026-10-25', label: 'Saturday, October 25 — Championships' },
] as const;
const STADIUM_TYPE = 'STADIUM_SITE';
const HOURS = [9, 10, 11, 12, 13, 14, 15, 16];

const slotKey = (areaId: string, date: string, hour: number) => `${areaId}|${date}|${hour}`;
const layoutKey = (areaId: string, date: string) => `${areaId}|${date}`;

const hourLabel = (hour: number) => (hour <= 11 ? `${hour}:00 AM` : hour === 12 ? '12:00 PM' : `${hour - 12}:00 PM`);
const displayHour = (hour: number) => {
  if (hour === 12) return '12:00 PM';
  if (hour === 24 || hour === 0) return '12:00 AM';
  if (hour > 12) return `${hour - 12}:00 PM`;
  return `${hour}:00 AM`;
};

const formatDateLabel = (date: string) => new Date(`${date}T00:00:00`).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

const layoutLabel = (layout: string) => (layout === '2x53' ? 'Two Large Fields' : layout === '1x53_plus_2x30' ? 'One Large Field + Two Small Fields' : layout === '3x30' ? 'Three Small Fields' : 'Custom Layout');
const weekForDate = (date: string) => HOSTING_DATES.findIndex((d) => d.date === date) + 1;

const STATUS_BADGE: Record<string, string> = {
  Hosting: 'bg-emerald-100 text-emerald-800',
  Away: 'bg-slate-100 text-slate-700',
  Partial: 'bg-amber-100 text-amber-800',
  Missing: 'bg-rose-100 text-rose-800',
};

const READINESS_DEFINITIONS: Record<string, string> = {
  READY: 'Hosting community assigned, fields configured, slots generated, no blocking conflicts, and scheduler-ready.',
  PARTIAL: 'Some hosting data exists, but setup is incomplete and scheduling may fail for some divisions.',
  'NOT READY': 'Insufficient data to schedule games.',
};

const INDICATOR_DEFINITIONS: Record<string, string> = {
  'incomplete hosting setup': 'Core setup exists, but at least one required part (community, field setup, or slots) is missing or incomplete.',
  'field inventory mismatch': 'Fields are configured but could not be resolved into schedulable small/large inventory for this host location.',
  'no large field available': 'No large-field capacity is configured for this host week.',
  'insufficient small fields': 'Small-field capacity is below the expected minimum for reliable scheduling.',
  'insufficient total slots': 'Total playable slot hours are below the minimum needed for expected games.',
  'overlapping slot conflicts': 'Two or more slot ranges overlap and create conflicting start times.',
  'host assignment missing': 'No valid hosting community assignment is attached to this availability row.',
  'scheduling window too short': 'The playable window is too short for a full game-day schedule.',
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default function HostingAvailabilityManager() {
  const [message, setMessage] = useState('');
  const [type, setType] = useState<'ok' | 'err'>('ok');
  const [orgs, setOrgs] = useState<any[]>([]);
  const [hosts, setHosts] = useState<any[]>([]);
  const [areas, setAreas] = useState<any[]>([]);
  const [configs, setConfigs] = useState<any[]>([]);
  const [selectedDates, setSelectedDates] = useState<string[]>([]);
  const [orgId, setOrgId] = useState('');
  const [hostId, setHostId] = useState('');
  const [selectedSlots, setSelectedSlots] = useState<Record<string, boolean>>({});
  const [activeConfigByAreaDate, setActiveConfigByAreaDate] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAvailability, setSavedAvailability] = useState<any[]>([]);
  const [generatedSlots, setGeneratedSlots] = useState<any[]>([]);
  const [generationDebug, setGenerationDebug] = useState<{ field_instances: number; slots: number } | null>(null);
  const [savedDateFilter, setSavedDateFilter] = useState('');
  const [savedSiteTypeFilter, setSavedSiteTypeFilter] = useState('');
  const [savedLayoutFilter, setSavedLayoutFilter] = useState('');

  const user = getAuthUser();
  const token = getToken();
  const searchParams = useSearchParams();
  const preselectedHostId = searchParams.get('host_location_id') || '';
  const preselectedOrgId = searchParams.get('organization_id') || '';

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [o, h, a, c] = await Promise.all([
          apiFetch('/organizations?page_size=500', {}, token),
          apiFetch('/host-locations?page_size=500&is_active=true', {}, token),
          apiFetch('/physical-field-areas?page_size=1000', {}, token),
          apiFetch('/field-configuration-options?page_size=2000', {}, token),
        ]);
        setOrgs(o.items || []);
        setHosts(h.items || []);
        setAreas(a.items || []);
        setConfigs(c.items || []);
        if (user?.role_name === 'community_scheduler') setOrgId(user.organization_id || '');
        else if (preselectedOrgId) setOrgId(preselectedOrgId);
        if (preselectedHostId) setHostId(preselectedHostId);
      } catch (e: any) {
        setMessage(e.message || 'Failed to load');
        setType('err');
      } finally {
        setLoading(false);
      }
    })();
  }, [preselectedHostId, preselectedOrgId]);

  const hostOptions = useMemo(() => hosts.filter((h: any) => !orgId || h.organization_id === orgId), [hosts, orgId]);
  const selectedHost = useMemo(() => hostOptions.find((h: any) => h.id === hostId), [hostId, hostOptions]);
  const visibleAreas = useMemo(() => areas.filter((a: any) => a.is_active && (!hostId || a.host_location_id === hostId)), [areas, hostId]);
  const configsByArea = useMemo(
    () => configs.filter((c: any) => c.is_active).reduce((m: any, c: any) => ((m[c.physical_field_area_id] = [...(m[c.physical_field_area_id] || []), c]), m), {}),
    [configs],
  );

  useEffect(() => {
    if (!hostOptions.some((h: any) => h.id === hostId)) setHostId('');
  }, [hostOptions, hostId]);

  const getSelectedConfigId = (areaId: string, date: string, defaultConfigId: string) =>
    activeConfigByAreaDate[layoutKey(areaId, date)] || defaultConfigId;

  const toggleHour = (a: string, d: string, h: number) =>
    setSelectedSlots((p) => ({ ...p, [slotKey(a, d, h)]: !p[slotKey(a, d, h)] }));

  const allDay = (a: string, d: string) => HOURS.every((h) => selectedSlots[slotKey(a, d, h)]);

  const toggleAllDay = (a: string, d: string, on: boolean) =>
    setSelectedSlots((p) => {
      const n = { ...p };
      for (const h of HOURS) n[slotKey(a, d, h)] = on;
      return n;
    });

  const summaryRanges = (areaId: string, date: string) => {
    const hours = HOURS.filter((h) => selectedSlots[slotKey(areaId, date, h)]);
    if (!hours.length) return [];
    const ranges: Array<{ start: number; end: number }> = [];
    let start = hours[0];
    let prev = hours[0];
    for (let i = 1; i < hours.length; i += 1) {
      if (hours[i] !== prev + 1) {
        ranges.push({ start, end: prev + 1 });
        start = hours[i];
      }
      prev = hours[i];
    }
    ranges.push({ start, end: prev + 1 });
    return ranges;
  };

  const loadSavedAvailability = async () => {
    const params = new URLSearchParams();
    if (orgId) params.set('organization_id', orgId);
    if (hostId) params.set('host_location_id', hostId);
    if (savedDateFilter) params.set('available_date', savedDateFilter);
    if (savedSiteTypeFilter) params.set('site_type', savedSiteTypeFilter);
    if (savedLayoutFilter) params.set('layout', savedLayoutFilter);
    const data = await apiFetch(`/hosting-availabilities/saved?${params.toString()}`, {}, token);
    const items = data.items || [];
    items.forEach((row: any, index: number) => {
      console.log('[Hosting Summary] raw saved availability row', {
        index,
        row,
        hostLocationId: row?.hostLocationId ?? row?.host_location_id,
        hostLocationName: row?.hostLocationName ?? row?.host_location_name,
        fields: row?.fields,
        smallFieldCount: row?.smallFieldCount ?? row?.small_field_count ?? row?.small_field_capacity,
        largeFieldCount: row?.largeFieldCount ?? row?.large_field_count ?? row?.large_field_capacity,
      });
    });
    setSavedAvailability(items);
    if (hostId) {
      const slots = await apiFetch(`/hosting-availabilities/generated-slots?${params.toString()}`, {}, token);
      setGeneratedSlots(slots || []);
    } else {
      setGeneratedSlots([]);
    }
  };

  useEffect(() => {
    loadSavedAvailability().catch(() => setSavedAvailability([]));
  }, [hostId, orgId, savedDateFilter, savedSiteTypeFilter, savedLayoutFilter]);

  const editSaved = (entry: any) => {
    setSelectedDates([entry.available_date]);
    const nextSlots: Record<string, boolean> = {};
    const nextConfigs: Record<string, string> = {};
    const area = visibleAreas[0];
    if (!area) return;
    for (const range of entry.time_ranges) {
      const start = Number(range.start_time.slice(0, 2));
      const end = Number(range.end_time.slice(0, 2));
      for (let h = start; h < end; h += 1) nextSlots[slotKey(area.id, entry.available_date, h)] = true;
    }
    const cfg = (configsByArea[area.id] || []).find((c: any) => c.name === entry.available_layout);
    if (cfg) nextConfigs[layoutKey(area.id, entry.available_date)] = cfg.id;
    setSelectedSlots(nextSlots);
    setActiveConfigByAreaDate(nextConfigs);
  };

  const deleteSaved = async (entry: any) => {
    const prompt = `Delete availability for ${entry.host_location_name} on ${formatDateLabel(entry.available_date)}?`;
    if (!window.confirm(prompt)) return;
    await apiFetch(`/hosting-availabilities/saved?host_location_id=${hostId}&available_date=${entry.available_date}`, { method: 'DELETE' }, token);
    setMessage('Saved availability deleted.');
    setType('ok');
    await loadSavedAvailability();
  };

  const save = async () => {
    if (!selectedDates.length || !visibleAreas.length) {
      setType('err');
      setMessage('Select dates and hosting site first.');
      return;
    }
    setSaving(true);
    try {
      const slots: any[] = [];
      for (const area of visibleAreas) {
        const cfgs = configsByArea[area.id] || [];
        for (const d of selectedDates) {
          const configId = getSelectedConfigId(area.id, d, cfgs[0]?.id || '');
          if (!configId) continue;
          for (const h of HOURS) {
            if (selectedSlots[slotKey(area.id, d, h)]) {
              slots.push({
                physical_field_area_id: area.id,
                field_configuration_option_id: configId,
                available_date: d,
                start_time: `${String(h).padStart(2, '0')}:00:00`,
                end_time: `${String(h + 1).padStart(2, '0')}:00:00`,
                is_available: true,
              });
            }
          }
        }
      }
      const result = await apiFetch('/hosting-availabilities/bulk-upsert', { method: 'POST', body: JSON.stringify({ slots }) }, token);
      setGenerationDebug({ field_instances: result.generated_field_instances || 0, slots: result.generated_slots || 0 });
      setType('ok');
      setMessage('Availability saved successfully.');
      await loadSavedAvailability();
    } catch (e: any) {
      setType('err');
      setMessage(e.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const summaryRows = useMemo(() => {
    const rows = savedAvailability.map((entry: any) => {
      const week = weekForDate(entry.available_date);
      const smallFieldCount = entry.smallFieldCount ?? entry.small_field_count ?? entry.small_field_capacity ?? 0;
      const largeFieldCount = entry.largeFieldCount ?? entry.large_field_count ?? entry.large_field_capacity ?? 0;
      const starts = (entry.time_ranges || []).map((r: any) => Number(r.start_time.slice(0, 2)));
      const ends = (entry.time_ranges || []).map((r: any) => Number(r.end_time.slice(0, 2)));
      const firstStart = starts.length ? Math.min(...starts) : 99;
      const lastEnd = ends.length ? Math.max(...ends) : 0;
      const indicators: string[] = [];
      const totalSlotHours = (entry.time_ranges || []).reduce((n: number, r: any) => n + (Number(r.end_time.slice(0, 2)) - Number(r.start_time.slice(0, 2))), 0);
      const hasHostAssignment = Boolean(entry.organization_id || (String(entry.organization_name || '').trim() && !UUID_PATTERN.test(String(entry.organization_name || '').trim())));
      const hasSlots = (entry.time_ranges || []).length > 0;
      const hasFieldConfig = smallFieldCount + largeFieldCount > 0;

      if (!hasHostAssignment) indicators.push('host assignment missing');
      if (!hasFieldConfig || !hasSlots) indicators.push('incomplete hosting setup');
      const hasInventoryMismatch = Boolean(entry.has_field_inventory_mismatch);
      if (hasInventoryMismatch) indicators.push('field inventory mismatch');
      if (!hasInventoryMismatch && largeFieldCount < 1) indicators.push('no large field available');
      if (!hasInventoryMismatch && smallFieldCount < 2) indicators.push('insufficient small fields');
      if (totalSlotHours < 4) indicators.push('insufficient total slots');
      if (lastEnd > 0 && lastEnd < 14) indicators.push('scheduling window too short');
      const hasOverlap = (entry.time_ranges || []).some((r: any, i: number, arr: any[]) => {
        const start = Number(r.start_time.slice(0, 2));
        return arr.some((x: any, j: number) => j !== i && start >= Number(x.start_time.slice(0, 2)) && start < Number(x.end_time.slice(0, 2)));
      });
      if (hasOverlap) indicators.push('overlapping slot conflicts');

      const readiness = !hasHostAssignment || !hasFieldConfig || !hasSlots
        ? 'NOT READY'
        : indicators.length
          ? 'PARTIAL'
          : 'READY';

      return {
        ...entry,
        small_field_capacity: smallFieldCount,
        large_field_capacity: largeFieldCount,
        week,
        firstStart,
        lastEnd,
        readiness,
        indicators,
      };
    });
    return rows.sort((a: any, b: any) => (a.week - b.week) || (a.firstStart - b.firstStart) || String(a.organization_name || '').localeCompare(String(b.organization_name || '')));
  }, [savedAvailability]);

  const dashboardMetrics = useMemo(() => {
    const weeks = new Set(summaryRows.map((r: any) => r.week));
    const weeksMissingHosts = HOSTING_DATES.map((d) => weekForDate(d.date)).filter((w) => w > 0 && !weeks.has(w));
    const weeksMissingLarge = HOSTING_DATES.map((d) => weekForDate(d.date)).filter((w) => w > 0 && !summaryRows.some((r: any) => r.week === w && (r.large_field_capacity || 0) > 0));
    return {
      totalHostDates: summaryRows.length,
      totalCommunitiesHosting: new Set(summaryRows.map((r: any) => r.organization_name || r.host_location_name)).size,
      totalSmallFields: summaryRows.reduce((sum: number, r: any) => sum + (r.small_field_capacity || 0), 0),
      totalLargeFields: summaryRows.reduce((sum: number, r: any) => sum + (r.large_field_capacity || 0), 0),
      weeksMissingHosts,
      weeksMissingLarge,
    };
  }, [summaryRows]);

  const organizationsById = useMemo(() => new Map(orgs.map((o: any) => [o.id, o.name])), [orgs]);

  const resolveCommunityName = (organizationId?: string, organizationName?: string) => {
    const normalizedName = String(organizationName || '').trim();
    if (normalizedName && !UUID_PATTERN.test(normalizedName)) return normalizedName;
    if (organizationId) {
      const mappedName = organizationsById.get(organizationId);
      if (mappedName && !UUID_PATTERN.test(mappedName)) return mappedName;
    }
    return 'Unknown Community';
  };

  const weeklyMatrix = useMemo(() => {
    const communities = Array.from(new Set(hosts.map((h: any) => h.organization_id).filter(Boolean)))
      .map((organizationId: string) => ({
        organizationId,
        communityName: resolveCommunityName(organizationId, hosts.find((h: any) => h.organization_id === organizationId)?.organization_name),
      }))
      .sort((a: any, b: any) => a.communityName.localeCompare(b.communityName));

    return communities.map(({ organizationId, communityName }: any) => {
      const byWeek: Record<number, string> = {};
      HOSTING_DATES.forEach((d) => {
        const w = weekForDate(d.date);
        const rows = summaryRows.filter((r: any) => r.organization_id === organizationId && r.available_date === d.date);
        if (!rows.length) byWeek[w] = 'Missing';
        else if (rows.every((r: any) => r.readiness === 'READY')) byWeek[w] = 'Hosting';
        else byWeek[w] = 'Partial';
      });
      if (Object.values(byWeek).every((v) => v === 'Missing')) {
        HOSTING_DATES.forEach((d) => { byWeek[weekForDate(d.date)] = 'Away'; });
      }
      return { community: communityName, byWeek };
    });
  }, [hosts, summaryRows, organizationsById]);

  const readinessChecks = useMemo(() => {
    const projectedSmallGames = 12;
    const projectedLargeGames = 9;
    const projectedTotalSlots = 40;
    const totalSlots = summaryRows.reduce((sum: number, row: any) => sum + (row.time_ranges || []).reduce((n: number, r: any) => n + (Number(r.end_time.slice(0, 2)) - Number(r.start_time.slice(0, 2))), 0), 0);
    return {
      smallReady: dashboardMetrics.totalSmallFields >= projectedSmallGames,
      largeReady: dashboardMetrics.totalLargeFields >= projectedLargeGames,
      slotReady: totalSlots >= projectedTotalSlots,
      totalSlots,
    };
  }, [dashboardMetrics, summaryRows]);

  return (
    <div className='space-y-4'>
      <Toast message={message} type={type} />
      <h1 className='text-2xl font-bold'>Hosting Availability</h1>

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>1. Select Organization</h2>
        <select disabled={user?.role_name === 'community_scheduler'} value={orgId} onChange={(e) => setOrgId(e.target.value)} className='w-full rounded border p-2 md:w-1/2'>
          <option value=''>Select organization</option>
          {orgs.map((o: any) => (
            <option key={o.id} value={o.id}>{o.name}</option>
          ))}
        </select>
      </section>

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>2. Select Hosting Site</h2>
        <select value={hostId} onChange={(e) => setHostId(e.target.value)} className='w-full rounded border p-2 md:w-1/2'>
          <option value=''>Select hosting site</option>
          {hostOptions.map((h: any) => (
            <option key={h.id} value={h.id}>{h.name}</option>
          ))}
        </select>
      </section>

      {!orgId ? (
        <section className='space-y-4 rounded border p-4'>
          <h2 className='font-semibold'>League-wide Hosting Operations Dashboard</h2>
          <div className='grid gap-2 md:grid-cols-3'>
            <div className='rounded border bg-slate-50 p-3 text-sm'>Total host dates: <strong>{dashboardMetrics.totalHostDates}</strong></div>
            <div className='rounded border bg-slate-50 p-3 text-sm'>Total communities hosting: <strong>{dashboardMetrics.totalCommunitiesHosting}</strong></div>
            <div className='rounded border bg-slate-50 p-3 text-sm'>Total small fields: <strong>{dashboardMetrics.totalSmallFields}</strong></div>
            <div className='rounded border bg-slate-50 p-3 text-sm'>Total large fields: <strong>{dashboardMetrics.totalLargeFields}</strong></div>
            <div className='rounded border bg-rose-50 p-3 text-sm'>Weeks missing hosts: <strong>{dashboardMetrics.weeksMissingHosts.join(', ') || 'None'}</strong></div>
            <div className='rounded border bg-rose-50 p-3 text-sm'>Weeks missing large fields: <strong>{dashboardMetrics.weeksMissingLarge.join(', ') || 'None'}</strong></div>
          </div>
          <div className='rounded border p-3 text-sm'>
            <div className='font-medium'>Scheduling readiness checks</div>
            <ul className='mt-2 list-disc pl-5'>
              <li>Small fields (K/1st–4th/5th): {readinessChecks.smallReady ? '✅ Ready' : '⚠️ Not enough capacity'}</li>
              <li>Large fields (6th/7th, 8th, Girls 6th/7th/8th): {readinessChecks.largeReady ? '✅ Ready' : '⚠️ Not enough capacity'}</li>
              <li>Total projected slots support: {readinessChecks.slotReady ? `✅ Ready (${readinessChecks.totalSlots} slots)` : `⚠️ Not enough slots (${readinessChecks.totalSlots})`}</li>
            </ul>
          </div>
          <div className='overflow-auto'>
            <h3 className='mb-2 font-medium'>Hosting summary (week/date/community/site)</h3>
            <div className='mb-2 rounded border bg-slate-50 p-2 text-xs text-slate-700'>
              <div className='font-medium'>Readiness definitions</div>
              <ul className='list-disc pl-5'>
                {Object.entries(READINESS_DEFINITIONS).map(([state, definition]) => (
                  <li key={state}><strong>{state}</strong>: {definition}</li>
                ))}
              </ul>
            </div>
              <table className='min-w-full text-sm'>
              <thead><tr className='border-b text-left'><th className='p-2'>Week</th><th className='p-2'>Date</th><th className='p-2'>Community</th><th className='p-2'>Host location</th><th className='p-2'>Small fields</th><th className='p-2'>Large fields</th><th className='p-2'>First slot</th><th className='p-2'>Last slot</th><th className='p-2'>Readiness</th><th className='p-2'>Validation indicators</th></tr></thead>
              <tbody>
                {summaryRows.map((row: any, i: number) => (
                  <tr key={`${row.available_date}-${row.host_location_name}-${i}`} className='border-b'>
                    <td className='p-2'>Week {row.week}</td><td className='p-2'>{formatDateLabel(row.available_date)}</td><td className='p-2'>{resolveCommunityName(row.organization_id, row.organization_name)}</td><td className='p-2'>{row.host_location_name}</td><td className='p-2'>{row.smallFieldCount ?? row.small_field_count ?? row.small_field_capacity ?? 0}</td><td className='p-2'>{row.largeFieldCount ?? row.large_field_count ?? row.large_field_capacity ?? 0}</td><td className='p-2'>{row.firstStart === 99 ? '—' : displayHour(row.firstStart)}</td><td className='p-2'>{row.lastEnd === 0 ? '—' : displayHour(row.lastEnd)}</td><td className='p-2'><span title={READINESS_DEFINITIONS[row.readiness]} className='cursor-help underline decoration-dotted'>{row.readiness}</span></td><td className='p-2'>{row.indicators.length ? <ul className='space-y-1'>{row.indicators.map((indicator: string) => <li key={`${row.available_date}-${row.host_location_name}-${indicator}`} title={INDICATOR_DEFINITIONS[indicator]} className='cursor-help underline decoration-dotted'>• {indicator}</li>)}</ul> : 'None'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className='overflow-auto'>
            <h3 className='mb-2 font-medium'>Weekly hosting matrix</h3>
            <table className='min-w-full text-sm'>
              <thead><tr className='border-b text-left'><th className='p-2'>Community</th>{HOSTING_DATES.map((d) => <th key={d.date} className='p-2'>W{weekForDate(d.date)}</th>)}</tr></thead>
              <tbody>
                {weeklyMatrix.map((row: any) => (
                  <tr key={row.community} className='border-b'><td className='p-2 font-medium'>{row.community}</td>{HOSTING_DATES.map((d) => { const status = row.byWeek[weekForDate(d.date)] || 'Missing'; return <td key={d.date} className='p-2'><span className={`rounded px-2 py-1 text-xs ${STATUS_BADGE[status]}`}>{status}</span></td>; })}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>3. Hosting Site Setup</h2>
        {!hostId ? <p className='text-slate-500'>Select a hosting site to view configured layouts.</p> : (
          <div className='space-y-3'>
            {visibleAreas.map((area: any) => {
              const cfgs = configsByArea[area.id] || [];
              return (
                <div key={area.id} className='rounded border bg-slate-50 p-3'>
                  <div className='font-medium'>{area.name}</div>
                  <div className='text-sm text-slate-600'>{area.field_space_type === STADIUM_TYPE ? 'Stadium Site' : 'Grass/Park Site'}</div>
                  <ul className='mt-2 list-disc pl-6 text-sm'>
                    {cfgs.map((c: any) => <li key={c.id}>{layoutLabel(c.name)} ({c.thirty_yard_capacity} Small / {c.fifty_three_yard_capacity} Large)</li>)}
                  </ul>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>4. Select Hosting Dates</h2>
        <div className='grid gap-2 md:grid-cols-2 lg:grid-cols-4'>
          {HOSTING_DATES.map((d) => (
            <button key={d.date} onClick={() => setSelectedDates((p) => (p.includes(d.date) ? p.filter((x) => x !== d.date) : [...p, d.date]))} className={`rounded border p-3 text-left ${selectedDates.includes(d.date) ? 'border-emerald-600 bg-emerald-50' : ''}`}>
              {d.label}
            </button>
          ))}
        </div>
      </section>

      <section className='rounded border p-4 overflow-auto'>
        <h2 className='mb-2 font-semibold'>5–7. Hourly Availability + Layout Selection</h2>
        {loading || !hostId || !selectedDates.length ? <p className='text-slate-500'>Select hosting site and dates.</p> : selectedDates.map((date) => (
          <div key={date} className='mb-4'>
            <h3 className='mb-2 font-medium'>{HOSTING_DATES.find((x) => x.date === date)?.label || date}</h3>
            {visibleAreas.map((area: any) => {
              const cfgs = configsByArea[area.id] || [];
              const defaultCfg = cfgs[0]?.id || '';
              const selectedCfg = getSelectedConfigId(area.id, date, defaultCfg);
              const isStadium = area.field_space_type === STADIUM_TYPE;
              return (
                <div key={`${area.id}-${date}`} className='mb-4 rounded border p-3'>
                  <div className='mb-2 flex flex-col gap-2 md:flex-row md:items-center md:justify-between'>
                    <div>
                      <div className='font-semibold'>{area.name}</div>
                      <div className='text-sm text-slate-600'>{isStadium ? 'Stadium Site' : 'Grass/Park Site'}</div>
                    </div>
                    {isStadium ? (
                      <select className='rounded border p-2 text-sm' value={selectedCfg} onChange={(e) => setActiveConfigByAreaDate({ ...activeConfigByAreaDate, [layoutKey(area.id, date)]: e.target.value })}>
                        {cfgs.map((c: any) => <option key={c.id} value={c.id}>{layoutLabel(c.name)}</option>)}
                      </select>
                    ) : <div className='text-sm text-slate-700'>Layout uses saved site setup automatically.</div>}
                  </div>
                  <div className='mb-2'>
                    <label className='inline-flex items-center gap-2 text-sm font-medium'>
                      <input type='checkbox' checked={allDay(area.id, date)} onChange={(e) => toggleAllDay(area.id, date, e.target.checked)} /> All Day (9:00 AM–4:00 PM)
                    </label>
                  </div>
                  <div className='grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8'>
                    {HOURS.map((h) => {
                      const selected = selectedSlots[slotKey(area.id, date, h)];
                      return (
                        <button key={h} onClick={() => toggleHour(area.id, date, h)} className={`rounded border px-2 py-3 text-sm ${selected ? 'border-emerald-700 bg-emerald-600 text-white' : 'bg-white'}`}>
                          {hourLabel(h)}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </section>

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>Saved Availability</h2>
        <div className='mb-3 grid gap-2 md:grid-cols-4'>
          <input type='date' className='rounded border p-2' value={savedDateFilter} onChange={(e) => setSavedDateFilter(e.target.value)} />
          <select className='rounded border p-2' value={savedSiteTypeFilter} onChange={(e) => setSavedSiteTypeFilter(e.target.value)}><option value=''>All Site Types</option><option value='STADIUM_SITE'>Stadium Site</option><option value='GRASS_PARK_SITE'>Grass/Park Site</option></select>
          <select className='rounded border p-2' value={savedLayoutFilter} onChange={(e) => setSavedLayoutFilter(e.target.value)}><option value=''>All Layouts</option><option value='2x53'>Two Large Fields</option><option value='1x53_plus_2x30'>One Large Field + Two Small Fields</option><option value='3x30'>Three Small Fields</option></select>
        </div>
        {!hostId ? <p className='text-slate-500'>Select a hosting site to view saved availability.</p> : !savedAvailability.length ? <p className='text-slate-500'>No saved availability has been entered for this hosting site.</p> : <div className='space-y-3'>{savedAvailability.map((entry: any, idx: number) => (
          <div key={`${entry.available_date}-${idx}`} className='rounded border bg-slate-50 p-3 text-sm'>
            <div className='flex items-start justify-between gap-2'>
              <div><div className='font-semibold'>{formatDateLabel(entry.available_date)}</div><div>{entry.host_location_name}</div><div>{entry.site_type === 'STADIUM_SITE' ? 'Stadium Site' : 'Grass/Park Site'}</div><div>Available Layout: {layoutLabel(entry.available_layout)}</div><div>Capacity: {entry.small_field_capacity} Small Fields / {entry.large_field_capacity} Large Field</div></div>
              <div className='flex gap-2'><button onClick={() => editSaved(entry)} className='rounded border px-3 py-1'>Edit</button><button onClick={() => deleteSaved(entry)} className='rounded border border-red-300 px-3 py-1 text-red-700'>Delete</button></div>
            </div>
            <div className='mt-1'>Available:</div><ul className='list-disc pl-6'>{entry.time_ranges.map((range: any, rIdx: number) => <li key={rIdx}>{displayHour(Number(range.start_time.slice(0,2)))}–{displayHour(Number(range.end_time.slice(0,2)))}</li>)}</ul>
          </div>
        ))}</div>}
      </section>

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>Generated Slots</h2>
        {generationDebug ? (
          <div className='mb-2 rounded border bg-amber-50 p-2 text-sm'>
            Generated:
            <ul className='list-disc pl-6'>
              <li>{generationDebug.field_instances} field instances</li>
              <li>{generationDebug.slots} slots</li>
            </ul>
          </div>
        ) : null}
        {!hostId ? <p className='text-slate-500'>Select a hosting site to view generated slots.</p> : !generatedSlots.length ? <p className='text-slate-500'>No generated slots for this filter yet.</p> : (
          <div className='overflow-auto'>
            <table className='min-w-full text-sm'>
              <thead><tr className='border-b text-left'><th className='p-2'>Date</th><th className='p-2'>Hosting Site</th><th className='p-2'>Field Instance</th><th className='p-2'>Field Type</th><th className='p-2'>Start Time</th><th className='p-2'>End Time</th><th className='p-2'>Status</th></tr></thead>
              <tbody>
                {generatedSlots.map((slot: any) => (
                  <tr key={slot.id} className='border-b'>
                    <td className='p-2'>{formatDateLabel(slot.available_date)}</td>
                    <td className='p-2'>{slot.host_location_name}</td>
                    <td className='p-2'>{slot.field_instance_name}</td>
                    <td className='p-2'>{slot.field_type}</td>
                    <td className='p-2'>{displayHour(Number(slot.start_time.slice(0, 2)))}</td>
                    <td className='p-2'>{displayHour(Number(slot.end_time.slice(0, 2)))}</td>
                    <td className='p-2'>{slot.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>9. Availability Summary</h2>
        {!selectedDates.length || !selectedHost ? <p className='text-slate-500'>Select dates and hosting site to preview summary.</p> : (
          <div className='space-y-3'>
            {selectedDates.map((date) => visibleAreas.map((area: any) => {
              const cfgs = configsByArea[area.id] || [];
              const selectedCfg = cfgs.find((c: any) => c.id === getSelectedConfigId(area.id, date, cfgs[0]?.id || ''));
              const ranges = summaryRanges(area.id, date);
              if (!ranges.length) return null;
              return (
                <div key={`summary-${area.id}-${date}`} className='rounded border bg-slate-50 p-3 text-sm'>
                  <div className='font-medium'>{HOSTING_DATES.find((x) => x.date === date)?.label || date}</div>
                  <div>{selectedHost.name}</div>
                  <div>{selectedCfg?.name === '2x53' ? 'Two Large Fields' : selectedCfg?.name === '1x53_plus_2x30' ? 'One Large + Two Small Fields' : selectedCfg?.name === '3x30' ? 'Three Small Fields' : 'Custom Layout'}</div>
                  <div className='mt-1'>Available:</div>
                  <ul className='list-disc pl-6'>
                    {ranges.map((r, i) => <li key={i}>{displayHour(r.start)}–{displayHour(r.end)}</li>)}
                  </ul>
                </div>
              );
            }))}
          </div>
        )}
      </section>

      <button className='rounded bg-emerald-700 px-4 py-2 text-white' disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save Availability'}</button>
    </div>
  );
}
