'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { API_URL, ApiError, apiFetch } from '@/lib/api';
import { canPublishSchedule } from '@/lib/auth';
import { useAuthSession } from '@/components/AuthGate';
import { getDivisionLabel } from '@/lib/divisionLabel';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';
import CommunityLogo from '@/components/CommunityLogo';

const tabs = ['By Date', 'By Host Location', 'By Team', 'By Division'] as const;
type TabKey = (typeof tabs)[number];

export default function ScheduleManagementPage() {
  const { accessToken: token, currentUser: authUser } = useAuthSession();
  const canControlSchedulePublication = canPublishSchedule(authUser);
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
  const [error, setError] = useState('');
  const [publicationMessage, setPublicationMessage] = useState('');
  const [publishDiagnostics, setPublishDiagnostics] = useState<any | null>(null);
  const [publicationLoading, setPublicationLoading] = useState(false);

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
    const opts: any = await apiFetch('/manual-schedule-builder/options', {}, token);
    const orgs: any = await apiFetch('/organizations?page_size=500', {}, token);
    setOptions({
      ...opts,
      organizations: orgs.items || [],
      fields: opts.fields || [],
    });

    const [gameResponse, conflictResponse, publishDiagnosticsResult] = await Promise.allSettled([
      apiFetch(`/schedule-management/games${qs ? `?${qs}` : ''}`, {}, token),
      apiFetch('/schedule-management/conflicts', {}, token),
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

  };

  useEffect(() => {
    load().catch((e) => {
      setError(e instanceof ApiError ? e.message : 'Unable to load schedule management data.');
    });
  }, [qs]);


  const updateSchedulePublication = async (action: 'publish' | 'unpublish') => {
    const seasonId = publishDiagnostics?.season_id;
    if (!seasonId || !canControlSchedulePublication) return;
    setPublicationLoading(true);
    setError('');
    setPublicationMessage('');
    try {
      const result = await apiFetch(`/seasons/${seasonId}/${action}-schedule`, { method: 'POST' }, token);
      setPublishDiagnostics({ ...(publishDiagnostics || {}), ...(result as any) });
      setPublicationMessage(String((result as any)?.message || (action === 'unpublish' ? 'Schedule unpublished.' : 'Schedule published.')));
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : `Unable to ${action} schedule.`);
    } finally {
      setPublicationLoading(false);
    }
  };

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

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Schedule Management</h1>

      {error ? <div className='whitespace-pre-line rounded border border-red-300 bg-red-50 p-2 text-red-700'>{error}</div> : null}
      {publicationMessage ? <div className='rounded border border-emerald-300 bg-emerald-50 p-2 text-emerald-800'>{publicationMessage}</div> : null}

      {publishDiagnostics ? <div className='rounded border bg-slate-50 p-3 text-sm'>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div>
            <div className='font-semibold'>Season: {publishDiagnostics.season_name}</div>
            <div className='mt-1'>Schedule Publication Status: <span className='font-semibold'>{publishDiagnostics.schedule_published ? 'Published' : 'Unpublished'}</span></div>
          </div>
          {canControlSchedulePublication ? <div className='flex flex-wrap gap-2'>
            {publishDiagnostics.schedule_published ? (
              <button className='rounded bg-amber-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300' disabled={publicationLoading} onClick={() => updateSchedulePublication('unpublish')}>Unpublish Schedule</button>
            ) : (
              <button className='rounded bg-emerald-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300' disabled={publicationLoading} onClick={() => updateSchedulePublication('publish')}>Publish Schedule</button>
            )}
          </div> : null}
        </div>
        <div className='mt-2 grid grid-cols-2 gap-2 md:grid-cols-3'>
          <div>Saved Scheduled Games: <span className='font-semibold'>{publishDiagnostics.saved_games ?? publishDiagnostics.total_scheduled_games ?? 0}</span></div>
          <div>Authoritative Source: <span className='font-semibold'>Saved scheduled games</span></div>
          <div>Archived Games: <span className='font-semibold'>{publishDiagnostics.archived_games ?? 0}</span></div>
          <div>Validation: <span className='font-semibold'>{publishDiagnostics.publish_blocking_issue_count ? 'Blocking issues found' : 'Ready'}</span></div>
          <div>Games Checked: <span className='font-semibold'>{publishDiagnostics.publish_validation_games_checked_count ?? publishDiagnostics.saved_games ?? 0}</span></div>
          <div>Export Count: <span className='font-semibold'>{publishDiagnostics.export_games_count ?? publishDiagnostics.saved_games ?? 0}</span></div>
          <div>Validation Run: <span className='font-semibold'>{publishDiagnostics.publish_validation_run_id ? String(publishDiagnostics.publish_validation_run_id).slice(0, 8) : 'Current'}</span></div>
        </div>
        <p className={`mt-2 rounded p-2 ${publishDiagnostics.publish_blocking_issue_count ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-800'}`}>
          {publishDiagnostics.publish_validation_message || (publishDiagnostics.publish_blocking_issue_count ? 'Schedule validation found blocking issues. Please review the listed games before publishing.' : 'Schedule is ready to publish.')}
        </p>
        {publishDiagnostics.publish_blocking_issues?.length ? (
          <div className='mt-2 overflow-x-auto'>
            <table className='min-w-full border text-left text-xs'>
              <thead className='bg-white'>
                <tr>
                  <th className='border p-2'>Issue</th>
                  <th className='border p-2'>Scheduled Game</th>
                  <th className='border p-2'>Team</th>
                  <th className='border p-2'>Date</th>
                  <th className='border p-2'>Time</th>
                  <th className='border p-2'>Location</th>
                  <th className='border p-2'>Field</th>
                  <th className='border p-2'>Recommended Action</th>
                </tr>
              </thead>
              <tbody>
                {publishDiagnostics.publish_blocking_issues.map((issue: any, index: number) => {
                  const currentIssue = typeof issue === 'string' ? { issue_code: issue, summary: issue } : issue;
                  return (
                    <tr key={index}>
                      <td className='border p-2 font-semibold'>{currentIssue.issue_code || currentIssue.summary || 'VALIDATION_FAILURE'}</td>
                      <td className='border p-2'>{currentIssue.scheduled_game_id || 'Current game'}</td>
                      <td className='border p-2'>{currentIssue.team || '—'}</td>
                      <td className='border p-2'>{currentIssue.date ? formatDisplayDate(currentIssue.date) : '—'}</td>
                      <td className='border p-2'>{currentIssue.time ? formatDisplayTime(currentIssue.time) : '—'}</td>
                      <td className='border p-2'>{currentIssue.location || '—'}</td>
                      <td className='border p-2'>{currentIssue.field || '—'}</td>
                      <td className='border p-2'>{currentIssue.recommended_action || 'Open Manual Schedule Builder and correct the affected current saved scheduled game.'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
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
      </div>

      <div className='rounded border p-3'>
        <h2 className='mb-2 font-semibold'>Schedule Conflicts</h2>
        {conflicts.length === 0 ? <p>No schedule conflicts found.</p> : <ul className='list-disc pl-6'>{conflicts.map((conflict: any, index: number) => <li key={index}>{conflict.message}</li>)}</ul>}
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
                <div><strong>Matchup:</strong> <span className='inline-flex items-center gap-2'><CommunityLogo src={game.home_team_logo_url} name={game.home_team_community_name || game.home_team_name} altText={game.home_team_logo_alt_text} size={24} />{game.home_team_name || 'TBD'}</span> vs <span className='inline-flex items-center gap-2'><CommunityLogo src={game.away_team_logo_url} name={game.away_team_community_name || game.away_team_name} altText={game.away_team_logo_alt_text} size={24} />{game.away_team_name || 'TBD'}</span></div>
                <div><strong>Division:</strong> {game.division_name || 'N/A'}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
