'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { API_URL, ApiError, apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

const tabs = ['By Date', 'By Host Location', 'By Team', 'By Division'] as const;
type TabKey = (typeof tabs)[number];

type Severity = 'OK' | 'Info' | 'Warning' | 'Issue';

export default function ScheduleManagementPage() {
  const token = getToken();
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<TabKey>('By Date');
  const [options, setOptions] = useState<any>({
    divisions: [],
    teams: [],
    host_locations: [],
    organizations: [],
    fields: [],
    weeks: [],
  });
  const [filters, setFilters] = useState<any>({
    date: '',
    division_id: '',
    organization_id: '',
    host_location_id: '',
    field_id: '',
    team_id: '',
    week_id: searchParams.get('week_id') || '',
  });
  const [games, setGames] = useState<any[]>([]);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [quality, setQuality] = useState<any | null>(null);
  const [qualityLoading, setQualityLoading] = useState(true);
  const [qualityError, setQualityError] = useState('');
  const [error, setError] = useState('');
  const [publishDiagnostics, setPublishDiagnostics] = useState<any | null>(null);

  const qs = useMemo(
    () =>
      Object.entries(filters)
        .filter(([, value]) => value)
        .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`)
        .join('&'),
    [filters]
  );

  const load = async () => {
    setError('');
    setQualityError('');
    setQualityLoading(true);

    const opts: any = await apiFetch('/manual-schedule-builder/options', {}, token);
    const orgs: any = await apiFetch('/organizations?page_size=500', {}, token);
    setOptions({
      ...opts,
      organizations: orgs.items || [],
      fields: opts.fields || [],
    });

    const [gameResponse, conflictResponse, qualityResult, publishDiagnosticsResult] = await Promise.allSettled([
      apiFetch(`/schedule-management/games${qs ? `?${qs}` : ''}`, {}, token),
      apiFetch('/schedule-management/conflicts', {}, token),
      apiFetch(`/schedule-management/quality-report${qs ? `?${qs}` : ''}`, {}, token),
      apiFetch('/schedule-management/publish-diagnostics', {}, token),
    ]);

    if (gameResponse.status === 'rejected' || conflictResponse.status === 'rejected') {
      if (gameResponse.status === 'rejected') throw gameResponse.reason;
      if (conflictResponse.status === 'rejected') throw conflictResponse.reason;
    }

    setGames((gameResponse.value as any).items || []);
    setConflicts((conflictResponse.value as any).conflicts || []);

    if (publishDiagnosticsResult.status === 'fulfilled') {
      setPublishDiagnostics((publishDiagnosticsResult.value as any) || null);
    } else {
      setPublishDiagnostics(null);
    }

    if (qualityResult.status === 'fulfilled') {
      setQuality((qualityResult.value as any) || null);
    } else {
      setQuality(null);
      setQualityError('Unable to load schedule quality report.');
    }

    setQualityLoading(false);
  };

  useEffect(() => {
    load().catch((e) => {
      setQualityLoading(false);
      setError(e instanceof ApiError ? e.message : 'Unable to load schedule management data.');
    });
  }, [qs]);

  const exportCsv = async () => {
    try {
      const response = await fetch(`${API_URL}/schedule-management/export.csv${qs ? `?${qs}` : ''}`, {
        method: 'GET',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          Accept: 'text/csv',
        },
      });

      if (!response.ok) {
        throw new ApiError('Unable to export CSV.', response.status, await response.text());
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'schedule-export.csv';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Unable to export schedule CSV.');
    }
  };

  const statusClass = (status: Severity) => {
    if (status === 'OK') return 'bg-emerald-100 text-emerald-700';
    if (status === 'Info') return 'bg-sky-100 text-sky-700';
    if (status === 'Warning') return 'bg-amber-100 text-amber-700';
    return 'bg-red-100 text-red-700';
  };

  const grouped = useMemo(() => {
    const by: Record<string, any[]> = {};

    for (const game of games) {
      const groupKey =
        tab === 'By Date'
          ? (game.date ? formatDisplayDate(game.date) : 'No Date')
          : tab === 'By Host Location'
            ? game.host_location_name || 'Unassigned Host Location'
            : tab === 'By Team'
              ? `${game.home_team_name || 'Unknown'} vs ${game.away_team_name || 'Unknown'}`
              : game.division_name || 'Unknown Division';

      if (!by[groupKey]) by[groupKey] = [];
      by[groupKey].push(game);
    }

    return Object.entries(by);
  }, [games, tab]);

  const qualityDashboard = useMemo(() => {
    if (!quality) return null;

    const uneven = (quality.games_per_team || []).filter((r: any) => r.status !== 'OK');
    const repeat = quality.repeat_matchups || [];
    const zeroGames = quality.unscheduled_teams || [];
    const doubleHeaders = quality.double_headers || [];
    const nonBackToBack = doubleHeaders.filter((r: any) => !r.is_back_to_back);
    const lowUtilization = (quality.field_utilization || []).filter((r: any) => r.status !== 'OK');

    const issueSummary = [
      { key: 'conflicts', label: 'Conflicts', count: conflicts.length, severity: conflicts.length > 0 ? 'Issue' : 'OK', details: conflicts.map((c: any) => c.message) },
      { key: 'repeat_matchups', label: 'Repeat Matchups', count: repeat.length, severity: repeat.length > 0 ? 'Info' : 'OK', details: repeat.map((r: any) => `${r.team_a} vs ${r.team_b} (${r.games} games)`) },
      { key: 'zero_games', label: 'Teams with Zero Games', count: zeroGames.length, severity: zeroGames.length > 0 ? 'Issue' : 'OK', details: zeroGames.map((r: any) => `${r.team_name} (${r.division_name})`) },
      { key: 'uneven_counts', label: 'Uneven Game Counts', count: uneven.length, severity: uneven.length > 0 ? 'Info' : 'OK', details: uneven.map((r: any) => `${r.team_name}: ${r.games_scheduled} games (division avg ${r.division_average})`) },
      { key: 'double_headers', label: 'Double Headers', count: doubleHeaders.length, severity: doubleHeaders.length > 0 ? 'Info' : 'OK', details: doubleHeaders.map((r: any) => `${r.team_name} on ${formatDisplayDate(r.date)}: ${r.games} games`) },
      { key: 'non_back_to_back_double_headers', label: 'Non-Back-to-Back Double Headers', count: nonBackToBack.length, severity: nonBackToBack.length > 0 ? 'Issue' : 'OK', details: nonBackToBack.map((r: any) => `${r.team_name} on ${formatDisplayDate(r.date)}`) },
      { key: 'low_field_utilization', label: 'Low Field Utilization', count: lowUtilization.length, severity: lowUtilization.length > 0 ? 'Info' : 'OK', details: lowUtilization.flatMap((r: any) => {
        if (r.surface_type !== 'TURF_STADIUM') {
          return [`${r.host_location_name} ${formatDisplayDate(r.date)}: ${r.utilization_percent}%`];
        }
        const waveRows = (r.wave_utilization || []).map((wave: any) => {
          const available = (wave.available_field_components || []).map((c: any) => `${c.count} ${String(c.field_type || '').toLowerCase()}`).join(', ') || 'none';
          const unused = (wave.unused_components || []).map((c: any) => `${c.count} ${String(c.field_type || '').toLowerCase()}`).join(', ') || 'none';
          const games = (wave.games_placed || []).map((game: any) => `${game.home_team} vs ${game.away_team}`).join('; ') || 'none';
          const note = wave.optimization_note || 'UNUSED_COMPONENTS_REMAIN';
          return `${r.host_location_name} ${formatDisplayDate(r.date)} ${wave.start_time}-${wave.end_time} wave ${wave.sequence_number}: ${wave.layout || wave.preferred_layout_code}, available ${available}, games ${games}, unused ${unused}, utilization ${wave.utilization_percent}%, note ${note}`;
        });
        return waveRows.length ? waveRows : [`${r.host_location_name} ${formatDisplayDate(r.date)}: ${r.utilization_percent}% (idle ${r.idle_hours ?? 0}h)`];
      }) },
    ] as Array<{ key: string; label: string; count: number; severity: Severity; details: string[] }>;

    const hardErrorCount = Number(quality.final_validation_failure_count ?? issueSummary.filter((i) => i.severity === 'Issue').reduce((s, i) => s + i.count, 0));
    const sharedStatus = String(quality.schedule_quality_status || quality.final_validation_status || '').toUpperCase();

    let healthLabel = quality.overall_health || 'Excellent';
    let healthClass = 'bg-emerald-100 text-emerald-800 border-emerald-300';

    if (sharedStatus === 'BLOCKED' || sharedStatus === 'VALIDATION_FAILED' || hardErrorCount > 0) {
      healthLabel = 'Blocked';
      healthClass = 'bg-red-100 text-red-800 border-red-300';
    } else if (sharedStatus === 'PARTIAL_SUCCESS') {
      healthLabel = 'Partial';
      healthClass = 'bg-amber-100 text-amber-900 border-amber-300';
    }

    return { issueSummary, healthLabel, healthClass, sharedStatus, hardErrorCount };
  }, [quality, conflicts]);

  const exportQualityReportCsv = () => {
    if (!qualityDashboard) return;
    const rows: string[][] = [['Category', 'Count', 'Severity', 'Details']];
    for (const item of qualityDashboard.issueSummary) {
      rows.push([item.label, String(item.count), item.severity, item.details.join(' | ')]);
    }
    const csv = rows
      .map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'schedule-quality-report.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Schedule Management</h1>

      {error ? <div className='rounded border border-red-300 bg-red-50 p-2 text-red-700'>{error}</div> : null}

      {publishDiagnostics ? <div className='rounded border bg-slate-50 p-3 text-sm'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div><span className='font-semibold'>Season:</span> {publishDiagnostics.season_name} · <span className='font-semibold'>Schedule Status:</span> {String(publishDiagnostics.schedule_status || 'draft').toUpperCase()}</div>
          <div className='flex gap-2'>
            <button className='rounded bg-emerald-700 px-3 py-1 text-white' onClick={async()=>{ await apiFetch(`/seasons/${publishDiagnostics.season_id}/publish-schedule`, { method:'POST' }, token); await load(); }}>Publish Schedule</button>
            <button className='rounded border px-3 py-1' onClick={async()=>{ await apiFetch(`/seasons/${publishDiagnostics.season_id}/unpublish-schedule`, { method:'POST' }, token); await load(); }}>Unpublish</button>
          </div>
        </div>
        <div className='mt-2 grid grid-cols-2 gap-2 md:grid-cols-4'>
          <div>Total Scheduled Games: <span className='font-semibold'>{publishDiagnostics.total_scheduled_games ?? 0}</span></div>
          <div>Published Games: <span className='font-semibold'>{publishDiagnostics.published_games ?? 0}</span></div>
          <div>Draft Games: <span className='font-semibold'>{publishDiagnostics.draft_games ?? 0}</span></div>
          <div>Archived Games: <span className='font-semibold'>{publishDiagnostics.archived_games ?? 0}</span></div>
        </div>
      </div> : null}

      <div className='grid gap-2 md:grid-cols-7'>
        <input type='date' className='rounded border p-2' value={filters.date} onChange={(e) => setFilters({ ...filters, date: e.target.value })} aria-label='Date' />

        <select className='rounded border p-2' value={filters.division_id} onChange={(e) => setFilters({ ...filters, division_id: e.target.value })}>
          <option value=''>Division</option>
          {options.divisions.map((division: any) => (
            <option key={division.id} value={division.id}>
              {getDivisionLabel(division)}
            </option>
          ))}
        </select>

        <select className='rounded border p-2' value={filters.organization_id} onChange={(e) => setFilters({ ...filters, organization_id: e.target.value })}>
          <option value=''>Organization</option>
          {options.organizations.map((organization: any) => (
            <option key={organization.id} value={organization.id}>
              {organization.name}
            </option>
          ))}
        </select>

        <select className='rounded border p-2' value={filters.host_location_id} onChange={(e) => setFilters({ ...filters, host_location_id: e.target.value })}>
          <option value=''>Host Location</option>
          {options.host_locations.map((hostLocation: any) => (
            <option key={hostLocation.id} value={hostLocation.id}>
              {hostLocation.name}
            </option>
          ))}
        </select>

        <select className='rounded border p-2' value={filters.field_id} onChange={(e) => setFilters({ ...filters, field_id: e.target.value })}>
          <option value=''>Field</option>
          {options.fields.map((field: any) => (
            <option key={field.id} value={field.id}>
              {field.name}
            </option>
          ))}
        </select>

        <select className='rounded border p-2' value={filters.team_id} onChange={(e) => setFilters({ ...filters, team_id: e.target.value })}>
          <option value=''>Team</option>
          {options.teams.map((team: any) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </select>
        <select className='rounded border p-2' value={filters.week_id} onChange={(e) => setFilters({ ...filters, week_id: e.target.value })}>
          <option value=''>Week</option>
          {options.weeks.map((week: any) => (
            <option key={week.id} value={week.id}>
              {week.label || `Week ${week.week_number}`}
            </option>
          ))}
        </select>

      </div>

      <div className='flex flex-wrap gap-2'>
        {tabs.map((tabName) => (
          <button key={tabName} onClick={() => setTab(tabName)} className={`rounded px-3 py-1 ${tab === tabName ? 'bg-blue-600 text-white' : 'bg-slate-200'}`}>
            {tabName}
          </button>
        ))}
      </div>

      <div className='flex flex-wrap gap-2'>
        <button className='inline-block rounded bg-emerald-600 px-3 py-2 text-white' onClick={exportCsv}>Export CSV</button>
        <button className='inline-block rounded bg-indigo-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:opacity-60' onClick={exportQualityReportCsv} disabled={!qualityDashboard}>Export Quality Report CSV</button>
      </div>

      <div className='rounded border p-3'>
        <h2 className='mb-2 font-semibold'>Schedule Conflicts</h2>
        {conflicts.length === 0 ? <p>No schedule conflicts found.</p> : <ul className='list-disc pl-6'>{conflicts.map((conflict: any, index: number) => <li key={index}>{conflict.message}</li>)}</ul>}
      </div>

      <div className='space-y-4 rounded border p-3'>
        <h2 className='text-xl font-semibold'>Schedule Quality Report</h2>
        {qualityLoading ? (
          <p>Loading quality report...</p>
        ) : qualityError ? (
          <p>{qualityError}</p>
        ) : !quality || !qualityDashboard ? (
          <p>No quality report data available.</p>
        ) : (
          <>
            <div className={`rounded border p-3 ${qualityDashboard.healthClass}`}>
              <h3 className='font-semibold'>Overall Schedule Health Score: {qualityDashboard.healthLabel}</h3>
              <p className='mt-1 text-sm'>Final validation: {quality.final_validation_status || 'unknown'} · Schedule quality: {quality.schedule_quality_status || 'unknown'} · Hard-rule failures: {qualityDashboard.hardErrorCount}</p>
            </div>

            <section className='space-y-2'>
              <h3 className='font-semibold'>Issue Summary</h3>
              {qualityDashboard.issueSummary.map((item) => (
                <details key={item.key} className='rounded border p-2'>
                  <summary className='flex cursor-pointer items-center justify-between'>
                    <span>{item.label}: {item.count}</span>
                    <span className={`rounded px-2 py-0.5 text-sm ${statusClass(item.severity)}`}>{item.severity}</span>
                  </summary>
                  <div className='mt-2 text-sm'>
                    {item.details.length === 0 ? <p>No affected teams/games.</p> : <ul className='list-disc pl-5'>{item.details.map((detail, i) => <li key={i}>{detail}</li>)}</ul>}
                  </div>
                </details>
              ))}
            </section>

            <section className='space-y-2'>
              <h3 className='font-semibold'>Turf Wave Utilization</h3>
              {(quality.field_utilization || []).filter((row: any) => row.surface_type === 'TURF_STADIUM').length === 0 ? (
                <p className='text-sm text-slate-600'>No turf stadium waves found for this schedule.</p>
              ) : (
                <div className='overflow-x-auto'>
                  <table className='min-w-full border text-sm'>
                    <thead>
                      <tr className='border-b bg-slate-50 text-left'>
                        <th className='p-2'>Host</th>
                        <th className='p-2'>Date</th>
                        <th className='p-2'>Start</th>
                        <th className='p-2'>Wave</th>
                        <th className='p-2'>Layout</th>
                        <th className='p-2'>Assigned games</th>
                        <th className='p-2'>Capacity</th>
                        <th className='p-2'>Used</th>
                        <th className='p-2'>Unused</th>
                        <th className='p-2'>Utilization</th>
                        <th className='p-2'>Optimization note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(quality.field_utilization || []).filter((row: any) => row.surface_type === 'TURF_STADIUM').flatMap((row: any) => (row.wave_utilization || []).map((wave: any) => (
                        <tr key={`${wave.wave_id}-${wave.start_time}`} className='border-b align-top'>
                          <td className='p-2'>{wave.host_location || row.host_location_name}</td>
                          <td className='p-2'>{formatDisplayDate(wave.date || row.date)}</td>
                          <td className='p-2'>{wave.start_time}</td>
                          <td className='p-2'>{wave.wave_name || `Wave ${wave.sequence_number}`}</td>
                          <td className='p-2'>{wave.layout || wave.preferred_layout_code || '—'}</td>
                          <td className='p-2'>{(wave.assigned_games || wave.games_placed || []).map((game: any) => `${game.home_team} vs ${game.away_team}`).join('; ') || '—'}</td>
                          <td className='p-2'>{(wave.capacity_components || wave.available_field_components || []).map((c: any) => `${c.count} ${String(c.field_type || '').toLowerCase()}`).join(', ') || '—'}</td>
                          <td className='p-2'>{(wave.used_components || []).map((c: any) => `${c.count} ${String(c.field_type || '').toLowerCase()}`).join(', ') || `${wave.used_component_count ?? wave.assigned_slots ?? 0}`}</td>
                          <td className='p-2'>{(wave.unused_components || []).map((c: any) => `${c.count} ${String(c.field_type || '').toLowerCase()}`).join(', ') || `${wave.unused_component_count ?? wave.open_slots ?? 0}`}</td>
                          <td className='p-2'>{wave.utilization_percent ?? 0}%</td>
                          <td className='p-2'>{wave.optimization_note || 'UNUSED_COMPONENTS_REMAIN'}</td>
                        </tr>
                      )))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </div>

      <div className='space-y-3'>
        {grouped.map(([groupName, groupGames]) => (
          <div key={groupName} className='rounded border p-3'>
            <h3 className='mb-2 text-lg font-semibold'>{groupName}</h3>
            {(groupGames as any[]).map((game) => (
              <div key={game.id} className='mb-2 rounded border p-2'>
                <div><strong>Date:</strong> {game.date ? formatDisplayDate(game.date) : 'N/A'}</div>
                <div><strong>Host Location:</strong> {game.host_location_name || 'Unassigned'}</div>
                <div><strong>Field:</strong> {game.field || 'Unassigned'}</div>
                <div><strong>Time:</strong> {game.time ? formatDisplayTime(game.time) : 'N/A'}</div>
                <div><strong>Matchup:</strong> {game.home_team_name || 'TBD'} vs {game.away_team_name || 'TBD'}</div>
                <div><strong>Division:</strong> {game.division_name || 'N/A'}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
