'use client';

import { useEffect, useMemo, useState } from 'react';
import { API_URL, ApiError, apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';

const tabs = ['By Date', 'By Host Location', 'By Team', 'By Division'] as const;
type TabKey = (typeof tabs)[number];

type Severity = 'OK' | 'Warning' | 'Issue';

export default function ScheduleManagementPage() {
  const token = getToken();
  const [tab, setTab] = useState<TabKey>('By Date');
  const [options, setOptions] = useState<any>({
    divisions: [],
    teams: [],
    host_locations: [],
    organizations: [],
    fields: [],
  });
  const [filters, setFilters] = useState<any>({
    date: '',
    division_id: '',
    organization_id: '',
    host_location_id: '',
    field_id: '',
    team_id: '',
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
      throw gameResponse.status === 'rejected' ? gameResponse.reason : conflictResponse.reason;
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
    if (status === 'Warning') return 'bg-amber-100 text-amber-700';
    return 'bg-red-100 text-red-700';
  };

  const grouped = useMemo(() => {
    const by: Record<string, any[]> = {};

    for (const game of games) {
      const groupKey =
        tab === 'By Date'
          ? game.date || 'No Date'
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
      { key: 'repeat_matchups', label: 'Repeat Matchups', count: repeat.length, severity: repeat.length > 0 ? 'Warning' : 'OK', details: repeat.map((r: any) => `${r.team_a} vs ${r.team_b} (${r.games} games)`) },
      { key: 'zero_games', label: 'Teams with Zero Games', count: zeroGames.length, severity: zeroGames.length > 0 ? 'Issue' : 'OK', details: zeroGames.map((r: any) => `${r.team_name} (${r.division_name})`) },
      { key: 'uneven_counts', label: 'Uneven Game Counts', count: uneven.length, severity: uneven.length > 0 ? 'Warning' : 'OK', details: uneven.map((r: any) => `${r.team_name}: ${r.games_scheduled} games (division avg ${r.division_average})`) },
      { key: 'double_headers', label: 'Double Headers', count: doubleHeaders.length, severity: doubleHeaders.length > 0 ? 'Warning' : 'OK', details: doubleHeaders.map((r: any) => `${r.team_name} on ${r.date}: ${r.games} games`) },
      { key: 'non_back_to_back_double_headers', label: 'Non-Back-to-Back Double Headers', count: nonBackToBack.length, severity: nonBackToBack.length > 0 ? 'Issue' : 'OK', details: nonBackToBack.map((r: any) => `${r.team_name} on ${r.date}`) },
      { key: 'low_field_utilization', label: 'Low Field Utilization', count: lowUtilization.length, severity: lowUtilization.length > 0 ? 'Warning' : 'OK', details: lowUtilization.map((r: any) => `${r.host_location_name} ${r.date}: ${r.utilization_percent}%`) },
    ] as Array<{ key: string; label: string; count: number; severity: Severity; details: string[] }>;

    const issueCount = issueSummary.filter((i) => i.severity === 'Issue').reduce((s, i) => s + i.count, 0);
    const avoidableWarningKeys = new Set(['repeat_matchups', 'uneven_counts']);
    const warningCount = issueSummary
      .filter((i) => i.severity === 'Warning' && avoidableWarningKeys.has(i.key))
      .reduce((s, i) => s + i.count, 0);

    let healthLabel = 'Excellent';
    let healthClass = 'bg-emerald-100 text-emerald-800 border-emerald-300';

    if (issueCount > 0) {
      healthLabel = 'Blocked';
      healthClass = 'bg-red-100 text-red-800 border-red-300';
    } else if (warningCount > 0) {
      healthLabel = warningCount >= 5 ? 'Needs Review' : 'Good';
      healthClass = warningCount >= 5 ? 'bg-orange-100 text-orange-800 border-orange-300' : 'bg-amber-100 text-amber-800 border-amber-300';
    }

    return { issueSummary, healthLabel, healthClass };
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

      <div className='grid gap-2 md:grid-cols-6'>
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
          </>
        )}
      </div>

      <div className='space-y-3'>
        {grouped.map(([groupName, groupGames]) => (
          <div key={groupName} className='rounded border p-3'>
            <h3 className='mb-2 text-lg font-semibold'>{groupName}</h3>
            {(groupGames as any[]).map((game) => (
              <div key={game.id} className='mb-2 rounded border p-2'>
                <div><strong>Date:</strong> {game.date || 'N/A'}</div>
                <div><strong>Host Location:</strong> {game.host_location_name || 'Unassigned'}</div>
                <div><strong>Field:</strong> {game.field || 'Unassigned'}</div>
                <div><strong>Time:</strong> {game.time || 'N/A'}</div>
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
