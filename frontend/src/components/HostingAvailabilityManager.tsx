'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';
import Toast from './Toast';
import { useSearchParams } from 'next/navigation';

const HOSTING_DATES = [
  { date: '2026-09-06', label: '09/06/2026' },
  { date: '2026-09-13', label: '09/13/2026' },
  { date: '2026-09-20', label: '09/20/2026' },
  { date: '2026-09-27', label: '09/27/2026' },
  { date: '2026-10-04', label: '10/04/2026' },
  { date: '2026-10-11', label: '10/11/2026' },
  { date: '2026-10-18', label: '10/18/2026 — Playoffs' },
  { date: '2026-10-25', label: '10/25/2026 — Championships' },
] as const;
const STADIUM_TYPE = 'STADIUM_SITE';
const HOURS = [9, 10, 11, 12, 13, 14, 15, 16];

const slotKey = (areaId: string, date: string, hour: number) => `${areaId}|${date}|${hour}`;
const layoutKey = (areaId: string, date: string) => `${areaId}|${date}`;

const hourLabel = (hour: number) => formatDisplayTime(`${hour}:00`);
const displayHour = (hour: number) => formatDisplayTime(`${hour === 24 ? 0 : hour}:00`);

const formatDateLabel = (date: string) => formatDisplayDate(date);

const layoutLabel = (layout: string) => (layout === '2x53' || layout === 'TWO_LARGE' ? '2 Large' : layout === '1x53_plus_2x30' || layout === 'ONE_MEDIUM_TWO_SMALL' ? '1 Medium + 2 Small' : layout === 'ONE_LARGE_ONE_MEDIUM' ? '1 Large + 1 Medium' : layout === 'TWO_MEDIUM' ? '2 Medium' : layout === '3x30' || layout === 'THREE_SMALL' ? '3 Small' : layout === 'ONE_LARGE_ONE_SMALL' ? '1 Large + 1 Small' : layout === 'ONE_MEDIUM_ONE_SMALL' ? '1 Medium + 1 Small' : 'Custom Layout');
const weekForDate = (date: string) => HOSTING_DATES.findIndex((d) => d.date === date) + 1;

const STATUS_BADGE: Record<string, string> = {
  Hosting: 'bg-emerald-100 text-emerald-800',
  Away: 'bg-slate-100 text-slate-700',
  Partial: 'bg-amber-100 text-amber-800',
};

const WEEKLY_CAPACITY_REQUIREMENTS: Record<number, { projectedSmallGames: number; projectedLargeGames: number; projectedTotalSlots: number }> = {
  1: { projectedSmallGames: 12, projectedLargeGames: 9, projectedTotalSlots: 40 },
  2: { projectedSmallGames: 12, projectedLargeGames: 9, projectedTotalSlots: 40 },
  3: { projectedSmallGames: 12, projectedLargeGames: 9, projectedTotalSlots: 40 },
  4: { projectedSmallGames: 12, projectedLargeGames: 9, projectedTotalSlots: 40 },
  5: { projectedSmallGames: 12, projectedLargeGames: 9, projectedTotalSlots: 40 },
  6: { projectedSmallGames: 12, projectedLargeGames: 9, projectedTotalSlots: 40 },
  7: { projectedSmallGames: 8, projectedLargeGames: 6, projectedTotalSlots: 28 },
  8: { projectedSmallGames: 6, projectedLargeGames: 4, projectedTotalSlots: 20 },
};

const READINESS_DEFINITIONS: Record<string, string> = {
  READY: 'Hosting community assigned, host location assigned, fields configured, slots generated, no slot overlaps, required field sizes present, and projected games supported.',
  PARTIAL: 'Host site exists, but projected division demand may exceed compatible field capacity.',
  'NOT READY': 'Core hosting setup is missing (community, site, fields, or generated slots).',
};

const INDICATOR_DEFINITIONS: Record<string, string> = {
  'incomplete hosting setup': 'Core setup exists, but at least one required part (community, field setup, or slots) is missing or incomplete.',
  'host location missing': 'No host location is attached to this availability row.',
  'field inventory mismatch': 'Fields are configured but could not be resolved into schedulable small/large inventory for this host location.',
  'no large field available': 'At least one large field is required for this week based on scheduled divisions.',
  'no small field available': 'At least one small field is required for this week based on scheduled divisions.',
  'insufficient total slots': 'Combined compatible field slots are below projected total games for this week.',
  'insufficient small field slots': 'Small-field projected games exceed small-field slot capacity for this host week.',
  'insufficient large field slots': 'Large-field projected games exceed large-field slot capacity for this host week.',
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
  const [hostConfigs, setHostConfigs] = useState<any[]>([]);
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
        const [o, h, a, c, hc]: any[] = await Promise.all([
          apiFetch('/organizations?page_size=500', {}, token),
          apiFetch('/host-locations?page_size=500&is_active=true', {}, token),
          apiFetch('/physical-field-areas?page_size=1000', {}, token),
          apiFetch('/field-configuration-options?page_size=2000', {}, token),
          apiFetch('/host-location-configurations?page_size=2000', {}, token),
        ]);
        setOrgs(o.items || []);
        setHosts(h.items || []);
        setAreas(a.items || []);
        setConfigs(c.items || []);
        setHostConfigs(hc.items || []);
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
  const hostConfigsForSelectedHost = useMemo(() => hostConfigs.filter((c: any) => c.is_active && c.host_location_id === hostId), [hostConfigs, hostId]);
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
    const data: any = await apiFetch(`/hosting-availabilities/saved?${params.toString()}`, {}, token);
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
      const slots: any = await apiFetch(`/hosting-availabilities/generated-slots?${params.toString()}`, {}, token);
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
    try {
      await apiFetch(`/hosting-availabilities/saved/${entry.id}`, { method: 'DELETE' }, token);
      setSavedAvailability((prev: any[]) => prev.filter((item: any) => item.id !== entry.id));
      setMessage('Saved availability deleted.');
      setType('ok');
      await loadSavedAvailability();
    } catch (e: any) {
      setType('err');
      setMessage(e?.message || 'Unable to delete saved availability.');
    }
  };

  const save = async () => {
    if (!selectedDates.length || (!visibleAreas.length && !hostConfigsForSelectedHost.length)) {
      setType('err');
      setMessage('Select dates, hosting site, and field configuration first.');
      return;
    }
    setSaving(true);
    try {
      const slots: any[] = [];
      if (!visibleAreas.length && hostId) {
        for (const d of selectedDates) {
          const configId = getSelectedConfigId(hostId, d, hostConfigsForSelectedHost[0]?.id || '');
          if (!configId) continue;
          for (const range of summaryRanges(hostId, d)) {
            slots.push({
              organization_id: orgId,
              host_location_id: hostId,
              selected_configuration_id: configId,
              available_date: d,
              start_time: `${String(range.start).padStart(2, '0')}:00:00`,
              end_time: `${String(range.end).padStart(2, '0')}:00:00`,
              is_available: true,
            });
          }
        }
      }
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
      const result: any = await apiFetch('/hosting-availabilities/bulk-upsert', { method: 'POST', body: JSON.stringify({ slots }) }, token);
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
      const requirements = WEEKLY_CAPACITY_REQUIREMENTS[week] || { projectedSmallGames: 0, projectedLargeGames: 0, projectedTotalSlots: 0 };
      const smallFieldSlots = smallFieldCount * totalSlotHours;
      const largeFieldSlots = largeFieldCount * totalSlotHours;
      const projectedGames = requirements.projectedSmallGames + requirements.projectedLargeGames;
      const compatibleAvailableSlots = smallFieldSlots + largeFieldSlots;
      const smallFieldUtilizationPct = smallFieldSlots > 0 ? (requirements.projectedSmallGames / smallFieldSlots) * 100 : 0;
      const largeFieldUtilizationPct = largeFieldSlots > 0 ? (requirements.projectedLargeGames / largeFieldSlots) * 100 : 0;
      const overallUtilizationPct = compatibleAvailableSlots > 0 ? (projectedGames / compatibleAvailableSlots) * 100 : 0;
      const needsSmallField = requirements.projectedSmallGames > 0;
      const needsLargeField = requirements.projectedLargeGames > 0;
      const hasHostAssignment = Boolean(entry.organization_id || (String(entry.organization_name || '').trim() && !UUID_PATTERN.test(String(entry.organization_name || '').trim())));
      const hasHostLocation = Boolean(String(entry.host_location_name || '').trim());
      const hasSlots = (entry.time_ranges || []).length > 0;
      const hasFieldConfig = smallFieldCount + largeFieldCount > 0;

      if (!hasHostAssignment) indicators.push('host assignment missing');
      if (!hasHostLocation) indicators.push('host location missing');
      if (!hasFieldConfig || !hasSlots) indicators.push('incomplete hosting setup');
      const hasInventoryMismatch = Boolean(entry.has_field_inventory_mismatch);
      if (hasInventoryMismatch) indicators.push('field inventory mismatch');
      if (!hasInventoryMismatch && needsLargeField && largeFieldCount < 1) indicators.push('no large field available');
      if (!hasInventoryMismatch && needsSmallField && smallFieldCount < 1) indicators.push('no small field available');
      if (!hasInventoryMismatch && requirements.projectedSmallGames > smallFieldSlots) indicators.push('insufficient small field slots');
      if (!hasInventoryMismatch && requirements.projectedLargeGames > largeFieldSlots) indicators.push('insufficient large field slots');
      if (compatibleAvailableSlots < projectedGames) indicators.push('insufficient total slots');
      if (lastEnd > 0 && lastEnd < 14) indicators.push('scheduling window too short');
      const hasOverlap = (entry.time_ranges || []).some((r: any, i: number, arr: any[]) => {
        const start = Number(r.start_time.slice(0, 2));
        return arr.some((x: any, j: number) => j !== i && start >= Number(x.start_time.slice(0, 2)) && start < Number(x.end_time.slice(0, 2)));
      });
      if (hasOverlap) indicators.push('overlapping slot conflicts');

      const capacityMissing = compatibleAvailableSlots <= 0;
      const capacityShortByType = indicators.includes('insufficient small field slots') || indicators.includes('insufficient large field slots');
      const readiness = !hasHostAssignment || !hasHostLocation || !hasFieldConfig || !hasSlots || capacityMissing
        ? 'NOT READY'
        : capacityShortByType || indicators.length
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
        smallFieldSlots,
        largeFieldSlots,
        projectedGames,
        smallFieldUtilizationPct,
        largeFieldUtilizationPct,
        overallUtilizationPct,
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
        if (!rows.length) byWeek[w] = 'Away';
        else if (rows.every((r: any) => r.readiness === 'READY')) byWeek[w] = 'Hosting';
        else byWeek[w] = 'Partial';
      });
            return { community: communityName, byWeek };
    });
  }, [hosts, summaryRows, organizationsById]);
  const splitHostWeeks = useMemo(() => {
    const byWeek = new Map<number, Set<string>>();
    summaryRows.forEach((row: any) => {
      const week = Number(row.week || 0);
      if (!week) return;
      const orgKey = String(row.organization_id || row.organization_name || row.host_location_id || '').trim();
      if (!orgKey) return;
      if (!byWeek.has(week)) byWeek.set(week, new Set<string>());
      byWeek.get(week)!.add(orgKey);
    });
    const result: Record<number, boolean> = {};
    HOSTING_DATES.forEach((d) => {
      const w = weekForDate(d.date);
      result[w] = (byWeek.get(w)?.size || 0) > 1;
    });
    return result;
  }, [summaryRows]);

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

  const supportedDivisionsLabel = (smallFieldCount: number, largeFieldCount: number) => {
    if (smallFieldCount > 0 && largeFieldCount > 0) return 'Small + Large';
    if (smallFieldCount > 0) return 'Small Only';
    if (largeFieldCount > 0) return 'Large Only';
    return 'None';
  };

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
              <thead><tr className='border-b text-left'><th className='p-2'>Week</th><th className='p-2'>Date</th><th className='p-2'>Community</th><th className='p-2'>Host location</th><th className='p-2'>Small fields</th><th className='p-2'>Large fields</th><th className='p-2'>Supported Divisions</th><th className='p-2'>Small Field Slots</th><th className='p-2'>Large Field Slots</th><th className='p-2'>Projected Games</th><th className='p-2'>Small Field Utilization %</th><th className='p-2'>Large Field Utilization %</th><th className='p-2'>Overall Utilization %</th><th className='p-2'>First slot</th><th className='p-2'>Last slot</th><th className='p-2'>Readiness</th><th className='p-2'>Validation indicators</th></tr></thead>
              <tbody>
                {summaryRows.map((row: any, i: number) => (
                  <tr key={`${row.available_date}-${row.host_location_name}-${i}`} className='border-b'>
                    <td className='p-2'>Week {row.week}</td><td className='p-2'>{formatDateLabel(row.available_date)}</td><td className='p-2'>{resolveCommunityName(row.organization_id, row.organization_name)}</td><td className='p-2'>{row.host_location_name}</td><td className='p-2'>{row.smallFieldCount ?? row.small_field_count ?? row.small_field_capacity ?? 0}</td><td className='p-2'>{row.largeFieldCount ?? row.large_field_count ?? row.large_field_capacity ?? 0}</td><td className='p-2'>{supportedDivisionsLabel(row.smallFieldCount ?? row.small_field_count ?? row.small_field_capacity ?? 0, row.largeFieldCount ?? row.large_field_count ?? row.large_field_capacity ?? 0)}</td><td className='p-2'>{row.smallFieldSlots}</td><td className='p-2'>{row.largeFieldSlots}</td><td className='p-2'>{row.projectedGames}</td><td className='p-2'>{row.smallFieldUtilizationPct.toFixed(1)}%</td><td className='p-2'>{row.largeFieldUtilizationPct.toFixed(1)}%</td><td className='p-2'>{row.overallUtilizationPct.toFixed(1)}%</td><td className='p-2'>{row.firstStart === 99 ? '—' : displayHour(row.firstStart)}</td><td className='p-2'>{row.lastEnd === 0 ? '—' : displayHour(row.lastEnd)}</td><td className='p-2'><span title={READINESS_DEFINITIONS[row.readiness]} className={`cursor-help rounded px-2 py-1 text-xs font-medium ${row.readiness === 'READY' ? 'bg-emerald-100 text-emerald-800' : row.readiness === 'PARTIAL' ? 'bg-amber-100 text-amber-800' : 'bg-rose-100 text-rose-800'}`}>{row.readiness}</span></td><td className='p-2'>{row.indicators.length ? <ul className='space-y-1'>{row.indicators.map((indicator: string) => <li key={`${row.available_date}-${row.host_location_name}-${indicator}`} title={INDICATOR_DEFINITIONS[indicator]} className='cursor-help underline decoration-dotted'>• {indicator}</li>)}</ul> : 'None'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className='overflow-auto'>
            <h3 className='mb-2 font-medium'>Weekly hosting matrix</h3>
            <table className='min-w-full text-sm'>
              <thead><tr className='border-b text-left'><th className='p-2'>Community</th>{HOSTING_DATES.map((d) => <th key={d.date} className='p-2'>W{weekForDate(d.date)}</th>)}<th className='p-2'>Split Host Week</th></tr></thead>
              <tbody>
                {weeklyMatrix.map((row: any) => (
                  <tr key={row.community} className='border-b'><td className='p-2 font-medium'>{row.community}</td>{HOSTING_DATES.map((d) => { const status = row.byWeek[weekForDate(d.date)] || 'Away'; return <td key={d.date} className='p-2'><span className={`rounded px-2 py-1 text-xs ${STATUS_BADGE[status]}`}>{status}</span></td>; })}<td className='p-2 text-xs text-slate-700'><ul className='space-y-1'>{HOSTING_DATES.map((d) => { const week = weekForDate(d.date); if (!splitHostWeeks[week]) return null; return <li key={`split-${row.community}-${week}`}>W{week}: Split Host Week: Yes</li>; })}</ul></td></tr>
                ))}
              </tbody>
            </table>
            <div className='mt-2 text-xs text-slate-600'>Dual Host Configuration is active for weeks where two or more communities host.</div>
          </div>
        </section>
      ) : null}

      <section className='rounded border p-4'>
        <h2 className='mb-2 font-semibold'>3. Hosting Site Setup</h2>
        {!hostId ? <p className='text-slate-500'>Select a hosting site to view configured layouts.</p> : (
          <div className='space-y-3'>
            {(visibleAreas.length ? visibleAreas : (selectedHost ? [{ id: selectedHost.id, name: selectedHost.name, field_space_type: selectedHost.surface_type, hostLevel: true }] : [])).map((area: any) => {
              const cfgs = area.hostLevel ? hostConfigsForSelectedHost.map((c: any) => ({ ...c, name: c.configuration_name, physical_field_area_id: area.id, thirty_yard_capacity: 0, fifty_three_yard_capacity: 0 })) : (configsByArea[area.id] || []);
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
            {(visibleAreas.length ? visibleAreas : (selectedHost ? [{ id: selectedHost.id, name: selectedHost.name, field_space_type: selectedHost.surface_type, hostLevel: true }] : [])).map((area: any) => {
              const cfgs = area.hostLevel ? hostConfigsForSelectedHost.map((c: any) => ({ ...c, name: c.configuration_name, physical_field_area_id: area.id })) : (configsByArea[area.id] || []);
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
                    {(isStadium || area.hostLevel) ? (
                      <select className='rounded border p-2 text-sm' value={selectedCfg} onChange={(e) => setActiveConfigByAreaDate({ ...activeConfigByAreaDate, [layoutKey(area.id, date)]: e.target.value })}>
                        {cfgs.map((c: any) => <option key={c.id} value={c.id}>{layoutLabel(c.name)}</option>)}
                      </select>
                    ) : <div className='text-sm text-slate-700'>Layout uses saved site setup automatically.</div>}
                  </div>
                  <div className='mb-2'>
                    <label className='inline-flex items-center gap-2 text-sm font-medium'>
                      <input type='checkbox' checked={allDay(area.id, date)} onChange={(e) => toggleAllDay(area.id, date, e.target.checked)} /> All Day (09:00 AM–04:00 PM)
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
          <select className='rounded border p-2' value={savedSiteTypeFilter} onChange={(e) => setSavedSiteTypeFilter(e.target.value)}><option value=''>All Site Types</option><option value='TURF_STADIUM'>Turf Stadium</option><option value='GRASS_FIELD'>Grass Field</option><option value='STADIUM_SITE'>Legacy Stadium Site</option><option value='GRASS_PARK_SITE'>Legacy Grass/Park Site</option></select>
          <select className='rounded border p-2' value={savedLayoutFilter} onChange={(e) => setSavedLayoutFilter(e.target.value)}><option value=''>All Layouts</option><option value='2x53'>Two Large Fields</option><option value='1x53_plus_2x30'>One Large Field + Two Small Fields</option><option value='3x30'>Three Small Fields</option><option value='TWO_LARGE'>Two Large</option><option value='ONE_MEDIUM_TWO_SMALL'>One Medium + Two Small</option><option value='TWO_MEDIUM'>Two Medium</option><option value='THREE_SMALL'>Three Small</option><option value='ONE_LARGE_ONE_MEDIUM'>One Large + One Medium</option><option value='ONE_LARGE_ONE_SMALL'>One Large + One Small</option><option value='ONE_MEDIUM_ONE_SMALL'>One Medium + One Small</option></select>
        </div>
        {!hostId ? <p className='text-slate-500'>Select a hosting site to view saved availability.</p> : !savedAvailability.length ? <p className='text-slate-500'>No saved availability has been entered for this hosting site.</p> : <div className='space-y-3'>{savedAvailability.map((entry: any, idx: number) => (
          <div key={`${entry.available_date}-${idx}`} className='rounded border bg-slate-50 p-3 text-sm'>
            <div className='flex items-start justify-between gap-2'>
              <div><div className='font-semibold'>{formatDateLabel(entry.available_date)}</div><div>{entry.host_location_name}</div><div>{entry.site_type === 'STADIUM_SITE' || entry.site_type === 'TURF_STADIUM' ? 'Turf Stadium' : 'Grass Field'}</div><div>Available Layout: {layoutLabel(entry.available_layout)}</div><div>Capacity: {entry.small_field_capacity} Small / {entry.medium_field_capacity || 0} Medium / {entry.large_field_capacity} Large</div></div>
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
            {selectedDates.map((date) => (visibleAreas.length ? visibleAreas : (selectedHost ? [{ id: selectedHost.id, name: selectedHost.name, hostLevel: true }] : [])).map((area: any) => {
              const cfgs = area.hostLevel ? hostConfigsForSelectedHost.map((c: any) => ({ ...c, name: c.configuration_name })) : (configsByArea[area.id] || []);
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
