'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

type ReadinessRow = {
  division_id: string;
  division_label: string;
  field_type_required: 'SMALL' | 'MEDIUM' | 'LARGE';
  number_of_teams: number;
  minimum_unique_matchups: number;
  target_scheduled_games: number | null;
  available_matching_slots: number;
  status: 'READY' | 'SHORT' | 'NO TEAMS';
};

type HostDateReadiness = {
  host_date: string;
  community_id: string | null;
  community_name: string | null;
  selected_host_locations: string[];
  host_sites_available: number;
  generated_slots: number;
  games_assigned: number;
  games_unscheduled: number;
  field_counts_by_size: Record<string, number>;
  warnings: string[];
  host_sites: Array<{
    host_location_id: string;
    host_location_name: string;
    community_id: string | null;
    community_name: string | null;
    surface_type: string;
    selected_turf_layout: string | null;
    grass_field_capacity: number;
    active_fields: string[];
    field_counts_by_size: Record<string, number>;
    total_field_capacity_by_size: Record<string, number>;
    generated_slots: number;
    games_assigned: number;
    games_assigned_by_location: number;
    games_unscheduled: number;
    divisions_supported: string[];
    warnings: string[];
    auto_select_turf_layout: boolean;
    lock_selected_layout: boolean;
    turf_wave_plan?: Array<{
      host_location_id: string;
      host_location_name: string;
      host_date: string;
      sequence_number: number;
      wave_intent: string;
      preferred_layout_code: string;
      start_time: string;
      end_time: string;
      transition_before_minutes: number;
      transition_after_minutes: number;
      generated_field_instances: string[];
      assigned_games: number;
      notes: string | null;
      slot_level_configurations: Array<{
        start_time: string;
        end_time: string;
        slot_level_configuration: string | null;
        field_instances_generated: string[];
        games_assigned_by_field_size: Record<string, number>;
        unused_compatible_capacity: Record<string, number>;
        inserted_through_slot_level_optimization: string[];
        rejected_assignments: string[];
        warnings: string[];
      }>;
      warnings: string[];
    }>;
  }>;
};

type ReadinessTotals = {
  total_teams: number;
  total_minimum_unique_matchups: number;
  total_target_scheduled_games: number | null;
  total_small_field_slots: number;
  total_medium_field_slots: number;
  total_large_field_slots: number;
  total_open_slots: number;
};

const MINIMUM_UNIQUE_MATCHUPS_HELP =
  'This represents the minimum number of unique matchups required for a single round-robin format before repeat matchups or double headers are considered.';

export default function ScheduleReadinessPage() {
  const token = getToken();
  const [rows, setRows] = useState<ReadinessRow[]>([]);
  const [totals, setTotals] = useState<ReadinessTotals | null>(null);
  const [error, setError] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [hostDates, setHostDates] = useState<HostDateReadiness[]>([]);
  const [hostingBalance, setHostingBalance] = useState<any[]>([]);
  const [hostingRotation, setHostingRotation] = useState<any[]>([]);
  const [fieldEfficiency, setFieldEfficiency] = useState<any[]>([]);
  const [weeklyDemand, setWeeklyDemand] = useState<any[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const data: any = await apiFetch('/schedule-readiness', {}, token);
        setRows(data?.rows || []);
        setTotals(data?.totals || null);
        setWarnings(data?.warnings || []);
        setHostDates(data?.host_dates || []);
        setHostingBalance(data?.hosting_balance || []);
        setHostingRotation(data?.hosting_rotation || []);
        setFieldEfficiency(data?.field_configuration_efficiency || []);
        setWeeklyDemand(data?.weekly_field_demand || []);
      } catch (e: any) {
        setError(e?.message || 'Failed to load schedule readiness report');
      }
    })();
  }, []);

  const statusClass = (status: ReadinessRow['status']) => {
    if (status === 'READY') return 'bg-green-100 text-green-700';
    if (status === 'SHORT') return 'bg-red-100 text-red-700';
    return 'bg-slate-100 text-slate-700';
  };

  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Schedule Readiness</h1>
      <p className='text-sm text-slate-600'>Capacity validation report only. This page does not create matchups or auto-schedule games.</p>
      {error ? <div className='rounded border border-red-200 bg-red-50 p-2 text-sm text-red-700'>{error}</div> : null}
      {warnings.length ? <div className='rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800'><div className='font-semibold'>Validation warnings</div><ul className='list-disc pl-5'>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
      {totals ? (
        <div className='grid gap-3 rounded border bg-white p-3 text-sm md:grid-cols-7'>
          <div><div className='text-slate-500'>Total Teams</div><div className='font-semibold'>{totals.total_teams}</div></div>
          <div><div className='text-slate-500'>Total Minimum Unique Matchups</div><div className='font-semibold'>{totals.total_minimum_unique_matchups}</div></div>
          <div><div className='text-slate-500'>Total Target Scheduled Games</div><div className='font-semibold'>{totals.total_target_scheduled_games ?? '—'}</div></div>
          <div><div className='text-slate-500'>Total Small Slots</div><div className='font-semibold'>{totals.total_small_field_slots}</div></div>
          <div><div className='text-slate-500'>Total Medium Slots</div><div className='font-semibold'>{totals.total_medium_field_slots}</div></div>
          <div><div className='text-slate-500'>Total Large Slots</div><div className='font-semibold'>{totals.total_large_field_slots}</div></div>
          <div><div className='text-slate-500'>Total Open Slots</div><div className='font-semibold'>{totals.total_open_slots}</div></div>
        </div>
      ) : null}



      <section className='rounded border bg-white p-3'>
        <h2 className='mb-2 font-semibold'>Community Hosting Equity Summary</h2>
        {!hostingBalance.length ? <p className='text-sm text-slate-500'>No active host availability found yet.</p> : (
          <div className='overflow-auto'>
            <table className='min-w-full text-sm'>
              <thead><tr className='border-b text-left'><th className='p-2'>Community</th><th className='p-2'>Host locations</th><th className='p-2'>Host weeks used</th><th className='p-2'>Games hosted</th><th className='p-2'>Avg games / host week</th><th className='p-2'>Last hosted week</th><th className='p-2'>Available weeks</th><th className='p-2'>Selected weeks</th><th className='p-2'>Hosting delta</th><th className='p-2'>Rotation rank</th><th className='p-2'>Status</th></tr></thead>
              <tbody>{hostingBalance.map((row) => <tr key={row.community_id || row.community} className='border-b'><td className='p-2'>{row.community}</td><td className='p-2'>{row.host_locations?.length ? row.host_locations.map((host: any) => host.host_location).join(', ') : '—'}</td><td className='p-2'>{row.host_weeks_used}</td><td className='p-2'>{row.games_hosted ?? row.games_hosted_season_to_date}</td><td className='p-2'>{row.average_games_per_host_week ?? 0}</td><td className='p-2'>{row.last_hosted_week || '—'}</td><td className='p-2'>{row.available_weeks?.length ? row.available_weeks.join(', ') : (row.available_host_weeks ?? row.available_host_dates)}</td><td className='p-2'>{row.selected_weeks?.length ? row.selected_weeks.join(', ') : '—'}</td><td className='p-2'>{row.hosting_delta}</td><td className='p-2'>{row.rotation_rank ?? '—'}</td><td className='p-2'>{row.status}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </section>

      <section className='rounded border bg-white p-3'>
        <h2 className='mb-2 font-semibold'>Weekly Community Host Plan</h2>
        {!hostingRotation.length ? <p className='text-sm text-slate-500'>No host rotation data found yet.</p> : (
          <div className='space-y-2'>
            {hostingRotation.map((row) => <div key={row.week} className='rounded border bg-slate-50 p-3 text-sm'>
              <div className='font-medium'>{row.week}</div>
              <div>Available communities: {row.available_communities?.length ? row.available_communities.join(', ') : '—'}</div>
              <div>Selected community or communities: {(row.selected_community_or_communities || row.selected_host_communities)?.length ? (row.selected_community_or_communities || row.selected_host_communities).join(', ') : '—'}</div>
              <div>Community capacity by field size: {row.community_capacity_by_field_size ? Object.entries(row.community_capacity_by_field_size).map(([community, capacity]: any) => `${community}: ${capacity.SMALL || 0} Small / ${capacity.MEDIUM || 0} Medium / ${capacity.LARGE || 0} Large`).join(' • ') : '—'}</div>
              <div>Locations used: {(row.locations_used_under_each_community || row.selected_host_locations_by_community || []).map((community: any) => `${community.community}: ${(community.locations || community.host_locations || []).map((host: any) => `${host.host_location} (${host.games_assigned || 0})`).join(', ')}`).join(' • ') || '—'}</div>
              {row.reason_additional_community_needed ? <div className='text-amber-800'>Additional community needed: {row.reason_additional_community_needed}</div> : null}
              <div className='mt-1 text-slate-600'>Rotation ranking: {(row.rotation_ranking || []).map((rank: any, index: number) => `${index + 1}. ${rank.community} (weeks ${rank.host_weeks_used}, last ${rank.last_hosted_week_number ? `W${rank.last_hosted_week_number}` : '—'}, games ${rank.games_hosted_season_to_date ?? rank.games_hosted}, expected ${rank.expected_games_hosted}, delta ${rank.hosting_delta}, capacity ${rank.capacity_score}, fit ${rank.capacity_fit_result})`).join(' • ') || '—'}</div>
              {row.reason_selected?.length ? <ul className='mt-2 list-disc pl-5 text-green-800'>{row.reason_selected.map((reason: string) => <li key={reason}>{reason}</li>)}</ul> : null}
              {row.reason_skipped?.length ? <ul className='mt-2 list-disc pl-5 text-amber-800'>{row.reason_skipped.map((reason: string) => <li key={reason}>{reason}</li>)}</ul> : null}
            </div>)}
          </div>
        )}
      </section>

      <section className='rounded border bg-white p-3'>
        <h2 className='mb-2 font-semibold'>Weekly Field Demand</h2>
        {!weeklyDemand.length ? <p className='text-sm text-slate-500'>No weekly demand or generated capacity found yet.</p> : (
          <div className='space-y-2'>
            {weeklyDemand.map((row) => <div key={row.host_date} className='rounded border bg-slate-50 p-3 text-sm'>
              <div className='font-medium'>{row.host_date}</div>
              <div>Required: {row.small_games_required} Small / {row.medium_games_required} Medium / {row.large_games_required} Large</div>
              <div>Capacity: {row.capacity_used ?? 0} used / {row.capacity_available ?? 0} available</div>
              <div className='mt-1 text-slate-600'>Available capacity by community and host location:</div>
              <ul className='list-disc pl-5'>{(row.available_capacity_by_community || []).map((community: any) => <li key={community.community_id}>{community.community}: {community.small_capacity} Small / {community.medium_capacity} Medium / {community.large_capacity} Large{community.host_locations?.length ? ` (${community.host_locations.map((host: any) => `${host.host_location}: ${host.small_capacity}/${host.medium_capacity}/${host.large_capacity}`).join('; ')})` : ''}</li>)}</ul>
            </div>)}
          </div>
        )}
      </section>

      <section className='rounded border bg-white p-3'>
        <h2 className='mb-2 font-semibold'>Field Configuration Efficiency</h2>
        {!fieldEfficiency.length ? <p className='text-sm text-slate-500'>No generated host-location slots found yet.</p> : (
          <div className='overflow-auto'>
            <table className='min-w-full text-sm'>
              <thead><tr className='border-b text-left'><th className='p-2'>Host location</th><th className='p-2'>Date</th><th className='p-2'>Selected turf layout</th><th className='p-2'>Small fields</th><th className='p-2'>Medium fields</th><th className='p-2'>Large fields</th><th className='p-2'>Field-size blocks</th><th className='p-2'>Layout changes</th><th className='p-2'>Transition windows</th><th className='p-2'>Unused capacity</th><th className='p-2'>Warnings</th></tr></thead>
              <tbody>{fieldEfficiency.map((row) => <tr key={`${row.host_location_id}-${row.host_date}`} className='border-b'><td className='p-2'>{row.host_location}</td><td className='p-2'>{row.host_date}</td><td className='p-2'>{row.selected_turf_layout || '—'}</td><td className='p-2'>{row.small_fields ?? 0}</td><td className='p-2'>{row.medium_fields ?? 0}</td><td className='p-2'>{row.large_fields ?? 0}</td><td className='p-2'>{row.field_size_blocks?.length ? row.field_size_blocks.join(', ') : '—'}</td><td className='p-2'>{row.layout_changes}</td><td className='p-2'>{row.transition_windows?.length ? row.transition_windows.join(', ') : row.transition_windows_required}</td><td className='p-2'>{row.unused_capacity ?? 0}</td><td className='p-2'>{row.warnings?.length ? row.warnings.join('; ') : '—'}</td></tr>)}</tbody>
            </table>
          </div>
        )}
      </section>

      <section className='rounded border bg-white p-3'>
        <h2 className='mb-2 font-semibold'>Host Date / Host Site Readiness</h2>
        {!hostDates.length ? <p className='text-sm text-slate-500'>No generated host-date slots found yet.</p> : (
          <div className='space-y-3'>
            {hostDates.map((day) => (
              <div key={day.host_date} className='rounded border bg-slate-50 p-3 text-sm'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <div>
                    <div className='font-semibold'>{day.host_date}</div>
                    <div className='text-slate-600'>Community: {day.community_name || 'Multiple communities'}</div>
                    <div className='text-slate-600'>Selected host locations: {day.selected_host_locations?.length ? day.selected_host_locations.join(', ') : '—'}</div>
                  </div>
                  <div>{day.host_sites_available} host site(s) • {day.generated_slots} generated slots • {day.games_assigned} assigned • {day.games_unscheduled} unscheduled</div>
                </div>
                {day.warnings.length ? <ul className='mt-2 list-disc pl-5 text-amber-800'>{day.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
                <div className='mt-3 grid gap-2 lg:grid-cols-2'>
                  {day.host_sites.map((site) => (
                    <div key={site.host_location_id} className='rounded border bg-white p-3'>
                      <div className='font-medium'>{site.host_location_name}</div>
                      <div className='text-slate-600'>Community: {site.community_name || '—'} • Surface: {site.surface_type}</div>
                      <div>Auto-selected turf layout: {site.selected_turf_layout || '—'}</div>
                      <div>Grass field capacity: {site.grass_field_capacity || 0}</div>
                      <div>Total field capacity by size: {site.field_counts_by_size.SMALL || 0} Small / {site.field_counts_by_size.MEDIUM || 0} Medium / {site.field_counts_by_size.LARGE || 0} Large</div>
                      <div>Slots: {site.generated_slots} • Games assigned by location: {site.games_assigned_by_location ?? site.games_assigned} • Unscheduled: {site.games_unscheduled}</div>
                      <div>Divisions: {site.divisions_supported.length ? site.divisions_supported.join(', ') : '—'}</div>
                      <div>{site.auto_select_turf_layout ? 'Auto-select layout enabled' : 'Manual layout'}{site.lock_selected_layout ? ' • Layout locked' : ''}</div>
                      {site.active_fields.length ? <div>Active fields: {site.active_fields.join(', ')}</div> : null}
                      {site.turf_wave_plan?.length ? (
                        <div className='mt-3 rounded border border-blue-100 bg-blue-50 p-2'>
                          <div className='font-semibold text-blue-900'>Turf Wave Plan</div>
                          <div className='space-y-2'>
                            {site.turf_wave_plan.map((wave) => (
                              <div key={`${wave.host_location_id}-${wave.host_date}-${wave.sequence_number}`} className='rounded bg-white p-2'>
                                <div className='font-medium'>Wave {wave.sequence_number}: {wave.wave_intent} • {wave.preferred_layout_code}</div>
                                <div className='text-slate-600'>{wave.start_time}–{wave.end_time} • transition {wave.transition_before_minutes}/{wave.transition_after_minutes} min • assigned {wave.assigned_games}</div>
                                <div className='text-slate-600'>Generated fields: {wave.generated_field_instances.length ? wave.generated_field_instances.join(', ') : '—'}</div>
                                {wave.slot_level_configurations.length ? (
                                  <div className='mt-2 overflow-auto'>
                                    <table className='min-w-full text-xs'>
                                      <thead><tr className='border-b text-left'><th className='p-1'>Slot</th><th className='p-1'>Config</th><th className='p-1'>Fields</th><th className='p-1'>Assigned</th><th className='p-1'>Unused compatible</th><th className='p-1'>Optimized inserts</th><th className='p-1'>Rejected / warnings</th></tr></thead>
                                      <tbody>{wave.slot_level_configurations.map((slot) => (
                                        <tr key={`${wave.sequence_number}-${slot.start_time}`} className='border-b align-top'>
                                          <td className='p-1'>{slot.start_time}–{slot.end_time}</td>
                                          <td className='p-1'>{slot.slot_level_configuration || 'Unsupported'}</td>
                                          <td className='p-1'>{slot.field_instances_generated.join(', ') || '—'}</td>
                                          <td className='p-1'>{slot.games_assigned_by_field_size.SMALL || 0} S / {slot.games_assigned_by_field_size.MEDIUM || 0} M / {slot.games_assigned_by_field_size.LARGE || 0} L</td>
                                          <td className='p-1'>{slot.unused_compatible_capacity.SMALL || 0} S / {slot.unused_compatible_capacity.MEDIUM || 0} M / {slot.unused_compatible_capacity.LARGE || 0} L</td>
                                          <td className='p-1'>{slot.inserted_through_slot_level_optimization.length ? slot.inserted_through_slot_level_optimization.join('; ') : '—'}</td>
                                          <td className='p-1'>{[...(slot.rejected_assignments || []), ...(slot.warnings || [])].length ? [...(slot.rejected_assignments || []), ...(slot.warnings || [])].join('; ') : '—'}</td>
                                        </tr>
                                      ))}</tbody>
                                    </table>
                                  </div>
                                ) : null}
                                {wave.warnings.length ? <ul className='mt-2 list-disc pl-5 text-amber-800'>{wave.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {site.warnings.length ? <ul className='mt-2 list-disc pl-5 text-amber-800'>{site.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className='overflow-auto rounded border bg-white'>
        <table className='min-w-full text-sm'>
          <thead>
            <tr className='border-b text-left'>
              <th className='p-2'>Division</th>
              <th className='p-2'>Field Type Required</th>
              <th className='p-2'>Number of Teams</th>
              <th className='p-2'>
                <span title={MINIMUM_UNIQUE_MATCHUPS_HELP} className='cursor-help underline decoration-dotted'>
                  Minimum Unique Matchups Needed
                </span>
              </th>
              <th className='p-2'>Target Scheduled Games</th>
              <th className='p-2'>Available Matching Slots</th>
              <th className='p-2'>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.division_id} className='border-b'>
                <td className='p-2'>{row.division_label}</td>
                <td className='p-2'>{row.field_type_required}</td>
                <td className='p-2'>{row.number_of_teams}</td>
                <td className='p-2'>{row.minimum_unique_matchups}</td>
                <td className='p-2'>{row.target_scheduled_games ?? '—'}</td>
                <td className='p-2'>{row.available_matching_slots}</td>
                <td className='p-2'><span className={`rounded px-2 py-1 text-xs font-semibold ${statusClass(row.status)}`}>{row.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
