'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ApiError, apiFetch } from '@/lib/api';
import { canManageSchedule, getAuthUser, getToken } from '@/lib/auth';
import { getDivisionLabel } from '@/lib/divisionLabel';
import { formatDisplayDate, formatDisplayDateTime, formatDisplayTime } from '@/lib/displayFormat';


type ScheduledGamesFilters = {
  date: string;
  time: string;
  division: string;
  hostLocation: string;
  field: string;
};

const emptyScheduledGamesFilters: ScheduledGamesFilters = {
  date: '',
  time: '',
  division: '',
  hostLocation: '',
  field: '',
};

const naturalCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

function uniqueByValue<T extends { value: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (!item.value || seen.has(item.value)) return false;
    seen.add(item.value);
    return true;
  });
}

function gameDateValue(game: any): string {
  return String(game?.game_date || '');
}


const TURF_FIELD_SLOT_LABELS = [
  'Small Field 1',
  'Small Field 2',
  'Small Field 3',
  'Medium Field 1',
  'Medium Field 2',
  'Large Field 1',
];
const INTERNAL_TURF_LAYOUT_PATTERN = /\b(?:THREE_SMALL|TWO_MEDIUM|ONE_SMALL_ONE_LARGE|TWO_SMALL_ONE_MEDIUM|ONE_LARGE|ONE_MEDIUM_TWO_SMALL|ONE_LARGE_ONE_MEDIUM|TWO_LARGE)\b/gi;

function cleanVisibleFieldLabel(rawValue: unknown): string {
  return String(rawValue || '')
    .trim()
    .replace(/^\s*Wave\s+\d+\s+/i, '')
    .replace(INTERNAL_TURF_LAYOUT_PATTERN, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function explicitFieldSlotLabel(value: any): string {
  const raw = cleanVisibleFieldLabel(value?.explicit_field_slot_label || value?.field_instance_name || value?.field_name || value?.field);
  return raw || String(value?.field_type ? `${value.field_type} Field` : 'Field');
}

function gameTimeValue(game: any): string {
  return String(game?.kickoff_time || '');
}

function gameDivisionValue(game: any): string {
  return String(game?.division_id || game?.division_name || '');
}

function gameHostLocationValue(game: any): string {
  return String(game?.host_location_id || game?.host_location_name || '');
}

function gameFieldValue(game: any): string {
  return explicitFieldSlotLabel(game);
}

function editableGameSnapshot(game: any): Record<string, unknown> {
  return {
    season_id: game?.season_id || null,
    week_id: game?.week_id || null,
    division_id: game?.division_id || '',
    home_team_id: game?.home_team_id || '',
    away_team_id: game?.away_team_id || '',
    host_location_id: game?.host_location_id || '',
    field_instance_id: game?.field_instance_id || game?.generated_field_instance_id || '',
    game_status_id: game?.game_status_id || null,
    game_date: game?.game_date || '',
    kickoff_time: game?.kickoff_time || '',
    public_notes: game?.public_notes || '',
    internal_admin_notes: game?.internal_admin_notes || '',
  };
}

function hasEditableGameChanges(game: any | null): boolean {
  if (!game?.__original) return false;
  return JSON.stringify(editableGameSnapshot(game)) !== JSON.stringify(game.__original);
}


type AutoScheduleDiagnosticsSummary = {
  status: string;
  message: string;
  rootCauses: string[];
  dryRun: boolean;
  gamesCommitted: number;
  previewGames: number;
  requiredGamesMissing: number;
  finalValidationStatus: string;
  scheduleQualityStatus: string;
  diagnosticsStatus: string;
  diagnosticsError: string;
  validationFailures: number;
  finalValidationFailures: unknown[];
  teamTimeConflicts: number;
  fieldTimeConflicts: number;
  doubleheaderBackToBackFailures: number;
  hostOwnerAsAwayGames: number;
  trueHomeHostHardRulePassed: string;
  totalHomeHostViolations: number;
  totalHomeHostExceptions: number;
  overflowLocationsUsed: number;
  latestStartTime: string;
  activeTimeWindow: string;
  pullForwardStarted: string;
  pullForwardCompleted: string;
  gamesMovedEarlier: number;
  skippedAttemptsByReason: Record<string, unknown>;
  failedValidationReasons: Record<string, unknown>;
  trueHomeHost: Record<string, unknown>;
  pullForward: Record<string, unknown>;
  rejectionReasons: Record<string, unknown>;
  preview: string;
  downloadUrl: string | null;
  downloadFilename: string;
};

function safeStringify(value: unknown, maxLength = 20000): string {
  try {
    const text = JSON.stringify(value, null, 2);
    if (text.length > maxLength) {
      return `${text.slice(0, maxLength)}\n... diagnostics truncated in UI ...`;
    }
    return text;
  } catch (error) {
    return 'Diagnostics payload too large to display. Use backend logs or export diagnostics instead.';
  }
}

function toNumber(value: unknown): number {
  return Number(value ?? 0) || 0;
}

function itemCount(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === 'object') return Object.keys(value as Record<string, unknown>).length;
  return toNumber(value);
}

function booleanLabel(value: unknown): string {
  if (value === true) return 'Yes';
  if (value === false) return 'No';
  if (value === null || value === undefined || value === '') return 'Unknown';
  return String(value);
}

function trueHomeHostRuleLabel(value: unknown): string {
  if (value === true) return 'Yes';
  if (value === false) return 'No';
  if (value === 'not_applicable') return 'Not applicable';
  if (value === 'not_run') return 'Not run';
  if (value === null || value === undefined || value === '') return 'Not run';
  return String(value);
}

function toStringArray(value: unknown, fallback: string[] = []): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item));
  if (typeof value === 'string' && value) return [value];
  return fallback;
}

function compactRecord(value: unknown, maxEntries = 20): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).slice(0, maxEntries));
}

function createDiagnosticsDownload(value: unknown): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const blob = new Blob([safeStringify(value, Number.MAX_SAFE_INTEGER)], { type: 'application/json' });
    return URL.createObjectURL(blob);
  } catch (error) {
    return null;
  }
}

function summarizeAutoScheduleDiagnostics(value: any): AutoScheduleDiagnosticsSummary {
  const diagnostics = value?.auto_schedule_diagnostics || {};
  const finalValidation = value?.final_validation || diagnostics?.final_validation || {};
  const hostVerification = value?.host_location_vs_home_team_verification || diagnostics?.host_location_vs_home_team_verification || {};
  const trueHomeHost = value?.true_home_host_diagnostics || diagnostics?.true_home_host_diagnostics || hostVerification;
  const pullForward = value?.pull_forward_diagnostics || diagnostics?.pull_forward_diagnostics || value?.pull_forward || diagnostics?.pull_forward || {};
  const skippedAttemptsByReason = compactRecord(value?.skipped_attempts_by_reason || diagnostics?.skipped_attempts_by_reason || {});
  const failedValidationReasons = compactRecord(value?.failed_validation_reasons || diagnostics?.failed_validation_reasons || {});
  const rejectionReasons = compactRecord(value?.rejection_diagnostics?.by_reason || diagnostics?.rejection_diagnostics?.by_reason || value?.rejections_by_reason || diagnostics?.rejections_by_reason || skippedAttemptsByReason);
  const requiredGamesMissing = itemCount(value?.required_games_still_missing ?? value?.required_games_missing ?? diagnostics?.required_games_still_missing ?? diagnostics?.required_games_missing);
  const validationFailures = toNumber(finalValidation?.final_validation_failure_count ?? value?.final_validation_failure_count ?? diagnostics?.final_validation_failure_count) || (itemCount(value?.validation_failures ?? value?.validation_errors ?? diagnostics?.validation_failures) + toNumber(value?.failed_validation_count ?? diagnostics?.failed_validation_count));
  const hostOwnerAwayGames = hostVerification?.host_owner_is_away_games ?? value?.host_owner_as_away_games ?? diagnostics?.host_owner_as_away_games;
  const filename = `auto-schedule-diagnostics-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;

  return {
    status: value?.status || finalValidation?.final_validation_status || 'unknown',
    finalValidationStatus: String(finalValidation?.final_validation_status ?? value?.final_validation_status ?? diagnostics?.final_validation_status ?? 'unknown'),
    scheduleQualityStatus: String(finalValidation?.schedule_quality_status ?? value?.schedule_quality_status ?? diagnostics?.schedule_quality_status ?? 'unknown'),
    diagnosticsStatus: String(finalValidation?.diagnostics_status ?? value?.diagnostics_status ?? diagnostics?.diagnostics_status ?? 'unknown'),
    diagnosticsError: String(finalValidation?.diagnostics_error ?? value?.diagnostics_error ?? diagnostics?.diagnostics_error ?? ''),
    message: value?.message || 'No message returned.',
    rootCauses: toStringArray(value?.root_cause_categories || diagnostics?.root_cause_categories, ['unknown']),
    dryRun: Boolean(value?.dry_run),
    gamesCommitted: toNumber(value?.committed_games_count ?? value?.total_games_created),
    previewGames: toNumber(value?.preview_games_count ?? diagnostics?.preview_games_count),
    requiredGamesMissing,
    validationFailures,
    finalValidationFailures: toStringArray(finalValidation?.final_validation_failures ?? value?.final_validation_failures ?? diagnostics?.final_validation_failures, []),
    teamTimeConflicts: itemCount(value?.team_time_conflicts ?? diagnostics?.team_time_conflicts),
    fieldTimeConflicts: itemCount(value?.field_time_conflicts ?? diagnostics?.field_time_conflicts),
    doubleheaderBackToBackFailures: itemCount(value?.doubleheader_back_to_back_failures ?? diagnostics?.doubleheader_back_to_back_failures),
    hostOwnerAsAwayGames: itemCount(hostOwnerAwayGames),
    trueHomeHostHardRulePassed: trueHomeHostRuleLabel(value?.true_home_host_rule_passed ?? diagnostics?.true_home_host_rule_passed ?? trueHomeHost?.true_home_host_rule_passed ?? value?.true_home_host_hard_rule_passed ?? diagnostics?.true_home_host_hard_rule_passed ?? trueHomeHost?.hard_rule_passed ?? trueHomeHost?.true_home_host_hard_rule_passed),
    totalHomeHostViolations: toNumber(value?.total_home_host_violations ?? diagnostics?.total_home_host_violations ?? trueHomeHost?.total_home_host_violations ?? trueHomeHost?.host_owner_is_away_team),
    totalHomeHostExceptions: toNumber(value?.total_home_host_exceptions ?? diagnostics?.total_home_host_exceptions ?? trueHomeHost?.total_home_host_exceptions),
    overflowLocationsUsed: itemCount(value?.overflow_locations_used ?? diagnostics?.overflow_locations_used),
    latestStartTime: String(value?.latest_start_time ?? diagnostics?.latest_start_time ?? 'Unknown'),
    activeTimeWindow: String(value?.active_time_window ?? diagnostics?.active_time_window ?? 'Unknown'),
    pullForwardStarted: booleanLabel(value?.pull_forward_started ?? diagnostics?.pull_forward_started ?? pullForward?.started),
    pullForwardCompleted: booleanLabel(value?.pull_forward_completed ?? diagnostics?.pull_forward_completed ?? pullForward?.completed),
    gamesMovedEarlier: toNumber(value?.games_moved_earlier ?? diagnostics?.games_moved_earlier ?? pullForward?.games_moved_earlier),
    skippedAttemptsByReason,
    failedValidationReasons,
    trueHomeHost: {
      true_home_host_checked_count: trueHomeHost?.true_home_host_checked_count ?? trueHomeHost?.total_games_checked ?? 0,
      true_home_host_violation_count: trueHomeHost?.true_home_host_violation_count ?? trueHomeHost?.total_home_host_violations ?? itemCount(trueHomeHost?.violations ?? trueHomeHost?.host_owner_is_away_games),
      true_home_host_exception_count: trueHomeHost?.true_home_host_exception_count ?? itemCount(trueHomeHost?.true_home_host_exceptions ?? trueHomeHost?.exceptions),
      true_home_host_rule_passed: trueHomeHostRuleLabel(trueHomeHost?.true_home_host_rule_passed ?? trueHomeHost?.hard_rule_passed ?? trueHomeHost?.true_home_host_hard_rule_passed),
      host_owner_is_away_team: trueHomeHost?.host_owner_is_away_team ?? itemCount(trueHomeHost?.host_owner_is_away_games),
    },
    pullForward: {
      candidates_considered: itemCount(pullForward?.candidates ?? pullForward?.candidate_games),
      candidates_accepted: toNumber(pullForward?.candidates_accepted ?? pullForward?.accepted_count),
      candidates_rejected: toNumber(pullForward?.candidates_rejected ?? pullForward?.rejected_count),
      games_moved_earlier: toNumber(pullForward?.games_moved_earlier),
    },
    rejectionReasons,
    preview: safeStringify({
      status: value?.status,
      message: value?.message,
      root_cause_categories: value?.root_cause_categories || diagnostics?.root_cause_categories,
      skipped_attempts_by_reason: skippedAttemptsByReason,
      failed_validation_reasons: failedValidationReasons,
      final_validation: finalValidation,
    }),
    downloadUrl: createDiagnosticsDownload(value),
    downloadFilename: filename,
  };
}

export default function ManualScheduleBuilderPage() {
  const token = getToken();
  const authUser = getAuthUser();
  const canManageGeneratedGames = canManageSchedule(authUser);
  const canBulkInlineEditScheduledGames = canManageSchedule(authUser);
  const searchParams = useSearchParams();
  const [options, setOptions] = useState<any>({ divisions: [], teams: [], host_locations: [], field_instances: [], seasons: [], weeks: [], organizations: [], game_statuses: [] });
  const [seasonId, setSeasonId] = useState(searchParams.get('season_id') || '');
  const [weekId, setWeekId] = useState(searchParams.get('week_id') || '');
  const [divisionId, setDivisionId] = useState('');
  const [homeTeamId, setHomeTeamId] = useState('');
  const [awayTeamId, setAwayTeamId] = useState('');
  const [slotId, setSlotId] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [hostLocationId, setHostLocationId] = useState('');
  const [slots, setSlots] = useState<any[]>([]);
  const [generatedSlots, setGeneratedSlots] = useState<any[]>([]);
  const [games, setGames] = useState<any[]>([]);
  const [suggestedMatchups, setSuggestedMatchups] = useState<any[]>([]);
  const [suggestedSlots, setSuggestedSlots] = useState<any[]>([]);
  const [allWeeklyMatchupsScheduled, setAllWeeklyMatchupsScheduled] = useState(false);
  const [noEligibleTeamMatchups, setNoEligibleTeamMatchups] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [autoFillPreview, setAutoFillPreview] = useState<any[]>([]);
  const [autoFillSkipped, setAutoFillSkipped] = useState<any[]>([]);
  const [autoFillLoading, setAutoFillLoading] = useState(false);
  const [schedulerDiagnostics, setSchedulerDiagnostics] = useState<any | null>(null);
  const [pendingGameEdits, setPendingGameEdits] = useState<Record<string, any>>({});
  const [moveGame, setMoveGame] = useState<any | null>(null);
  const [showClearScheduleModal, setShowClearScheduleModal] = useState(false);
  const [clearScheduleInput, setClearScheduleInput] = useState('');
  const [clearScheduleLoading, setClearScheduleLoading] = useState(false);
  const [showAutoScheduleSeasonModal, setShowAutoScheduleSeasonModal] = useState(false);
  const [clearExistingBeforeAutoSchedule, setClearExistingBeforeAutoSchedule] = useState(false);
  const [autoScheduleDryRun, setAutoScheduleDryRun] = useState(true);
  const [autoScheduleSeasonLoading, setAutoScheduleSeasonLoading] = useState(false);
  const [autoScheduleDiagnostics, setAutoScheduleDiagnostics] = useState<AutoScheduleDiagnosticsSummary | null>(null);
  const [scheduledGamesFilters, setScheduledGamesFilters] = useState<ScheduledGamesFilters>(emptyScheduledGamesFilters);
  const [isBulkEditMode, setIsBulkEditMode] = useState(false);

  useEffect(() => () => {
    if (autoScheduleDiagnostics?.downloadUrl) URL.revokeObjectURL(autoScheduleDiagnostics.downloadUrl);
  }, [autoScheduleDiagnostics?.downloadUrl]);

  useEffect(() => {
    [
      'optimizationPreview',
      'optimization-preview',
      'turfOptimizationState',
      'turf-optimization-state',
      'scheduleStateLabel',
      'scheduleViewMode',
      'manualScheduleBuilderScheduleMode',
    ].forEach((key) => {
      window.localStorage.removeItem(key);
      window.sessionStorage.removeItem(key);
    });
  }, []);

  const division = useMemo(() => options.divisions.find((d: any) => d.id === divisionId), [options, divisionId]);
  const divisionTeams = useMemo(() => options.teams.filter((t: any) => t.division_id === divisionId && t.is_active), [options, divisionId]);
  const seasonWeeks = useMemo(() => options.weeks.filter((w: any) => w.season_id === seasonId), [options, seasonId]);
  const canSave = Boolean(canManageGeneratedGames && seasonId && weekId && divisionId && homeTeamId && awayTeamId && slotId);
  const scheduledStatusId = useMemo(() => {
    const statuses = options.game_statuses || [];
    return statuses.find((status: any) => String(status.code || '').toUpperCase() === 'SCHEDULED')?.id || statuses[0]?.id || null;
  }, [options.game_statuses]);
  const buildEditableGame = (game: any) => {
    const pendingEdit = {
      ...game,
      division_id: game.division_id,
      field_instance_id: game.field_instance_id || game.generated_field_instance_id || '',
      host_location_id: game.host_location_id || '',
      game_status_id: game.game_status_id || scheduledStatusId,
      public_notes: game.public_notes || '',
      internal_admin_notes: game.internal_admin_notes || '',
    };
    return { ...pendingEdit, __original: editableGameSnapshot(pendingEdit) };
  };
  const seasonDateOptions = useMemo(() => {
    const dates = options.weeks.filter((w: any) => !seasonId || w.season_id === seasonId).map((w: any) => w.primary_game_date || w.start_date).filter(Boolean);
    games.forEach((game: any) => { if (game?.game_date) dates.push(game.game_date); });
    return Array.from(new Set(dates)).sort();
  }, [options.weeks, seasonId, games]);
  const validStartTimeOptions = useMemo(() => {
    const configuredTimes = generatedSlots
      .filter((slot: any) => !seasonId || slot.season_id === seasonId)
      .map((slot: any) => slot.start_time)
      .filter(Boolean);
    games.forEach((game: any) => { if (game?.kickoff_time) configuredTimes.push(game.kickoff_time); });
    return Array.from(new Set(configuredTimes)).sort();
  }, [generatedSlots, games, seasonId]);
  const scheduledGamesFilterOptions = useMemo(() => {
    const divisionOrder = new Map<string, number>((options.divisions || []).map((division: any, index: number) => [String(division.id), index]));
    const dates = uniqueByValue(games.map((game: any) => ({ value: gameDateValue(game), label: formatDisplayDate(game.game_date) })))
      .sort((a, b) => a.value.localeCompare(b.value));
    const times = uniqueByValue(games.map((game: any) => ({ value: gameTimeValue(game), label: formatDisplayTime(game.kickoff_time) })))
      .sort((a, b) => a.value.localeCompare(b.value));
    const divisions = uniqueByValue(games.map((game: any) => ({ value: gameDivisionValue(game), label: game.division_name || 'Unknown Division' })))
      .sort((a, b) => {
        const aOrder = divisionOrder.get(a.value);
        const bOrder = divisionOrder.get(b.value);
        if (aOrder !== undefined && bOrder !== undefined) return aOrder - bOrder;
        if (aOrder !== undefined) return -1;
        if (bOrder !== undefined) return 1;
        return naturalCollator.compare(a.label, b.label);
      });
    const hostLocations = uniqueByValue(games.map((game: any) => ({ value: gameHostLocationValue(game), label: game.host_location_name || '-' })))
      .sort((a, b) => naturalCollator.compare(a.label, b.label));
    const fieldSourceGames = scheduledGamesFilters.hostLocation
      ? games.filter((game: any) => gameHostLocationValue(game) === scheduledGamesFilters.hostLocation)
      : games;
    const fields = uniqueByValue(fieldSourceGames.map((game: any) => ({ value: explicitFieldSlotLabel(game), label: explicitFieldSlotLabel(game) || '-' })))
      .sort((a, b) => naturalCollator.compare(a.label, b.label));
    return { dates, times, divisions, hostLocations, fields };
  }, [games, options.divisions, scheduledGamesFilters.hostLocation]);
  const filteredGames = useMemo(() => games.filter((game: any) => (
    (!scheduledGamesFilters.date || gameDateValue(game) === scheduledGamesFilters.date) &&
    (!scheduledGamesFilters.time || gameTimeValue(game) === scheduledGamesFilters.time) &&
    (!scheduledGamesFilters.division || gameDivisionValue(game) === scheduledGamesFilters.division) &&
    (!scheduledGamesFilters.hostLocation || gameHostLocationValue(game) === scheduledGamesFilters.hostLocation) &&
    (!scheduledGamesFilters.field || explicitFieldSlotLabel(game) === scheduledGamesFilters.field)
  )), [games, scheduledGamesFilters]);
  const hasScheduledGamesFilters = Object.values(scheduledGamesFilters).some(Boolean);

  useEffect(() => {
    setScheduledGamesFilters((current) => {
      const next = { ...current };
      if (next.date && !scheduledGamesFilterOptions.dates.some((option) => option.value === next.date)) next.date = '';
      if (next.time && !scheduledGamesFilterOptions.times.some((option) => option.value === next.time)) next.time = '';
      if (next.division && !scheduledGamesFilterOptions.divisions.some((option) => option.value === next.division)) next.division = '';
      if (next.hostLocation && !scheduledGamesFilterOptions.hostLocations.some((option) => option.value === next.hostLocation)) next.hostLocation = '';
      if (next.field && !scheduledGamesFilterOptions.fields.some((option) => option.value === next.field)) next.field = '';
      if (Object.entries(next).every(([key, value]) => value === current[key as keyof ScheduledGamesFilters])) return current;
      return next;
    });
  }, [scheduledGamesFilterOptions]);

  const getWeekOptionLabel = (week: any) => {
    const baseLabel = week.label || `Week ${week.week_number}`;
    if (!week.start_date) return baseLabel;
    const formattedDate = formatDisplayDate(week.start_date);
    return `${baseLabel} — ${formattedDate}`;
  };

  const validationErrorMessages: Record<string, string> = {
    MISSING_REQUIRED_FIELDS: 'Unable to save: required game-day fields are missing.',
    SAME_TEAM_NOT_ALLOWED: 'Unable to save: home and away teams cannot be the same.',
    INVALID_TEAM_DIVISION_RELATIONSHIP: 'Unable to save: selected teams must belong to the selected division.',
    INVALID_GAME_STATUS: 'Unable to save: current game status is invalid.',
    INVALID_GAME_DATE: 'Unable to save: selected game date is invalid for this season.',
    INVALID_START_TIME: 'Unable to save: selected start time is invalid.',
    INVALID_HOST_LOCATION: 'Unable to save: selected host location is invalid.',
    INVALID_FIELD: 'Unable to save: selected field is invalid.',
    INVALID_FIELD_LOCATION_RELATIONSHIP: 'Unable to save: selected field does not belong to selected host location.',
    FIELD_TIME_CONFLICT: 'Unable to save: this exact field slot is already assigned at the selected date/time.',
    INVALID_TURF_FIELD_SLOT: 'Unable to save: selected turf field slot is invalid.',
    INVALID_TURF_FIELD_SLOT_COMBINATION: 'Unable to save: this turf field combination violates a hard physical field limit.',
  };

  const extractError = (e: unknown) => {
    if (e instanceof ApiError) {
      const detail = (e.details as any)?.detail;
      if (Array.isArray(detail)) return detail.map((x: any) => x?.msg || JSON.stringify(x)).join('; ');
      if (typeof detail === 'string') return detail;
      if (detail && typeof detail === 'object') {
        const errorCode = String(detail.error || '');
        if (errorCode === 'MISSING_REQUIRED_FIELDS' && Array.isArray(detail.fields)) {
          return `Unable to save: required ${detail.fields.join(', ')} ${detail.fields.length === 1 ? 'is' : 'are'} missing.`;
        }
        if ((errorCode === 'INVALID_TURF_FIELD_SLOT_COMBINATION' || errorCode === 'INVALID_TURF_FIELD_SLOT') && Array.isArray(detail.failure_reasons)) {
          if (detail.failure_reasons.includes('TWO_LARGE_FIELDS_NOT_ALLOWED_ON_ONE_TURF_SURFACE')) return 'Unable to save: this turf surface cannot support two Large fields at the same time.';
          if (detail.failure_reasons.includes('LARGE_FIELD_2_NOT_ALLOWED_ON_ONE_TURF_SURFACE')) return 'Unable to save: Large Field 2 is not valid for a single turf surface.';
          if (detail.failure_reasons.includes('DUPLICATE_EXPLICIT_FIELD_SLOT')) return 'Unable to save: this exact field slot is already assigned at the selected date/time.';
        }
        if (validationErrorMessages[errorCode]) return validationErrorMessages[errorCode];
        return JSON.stringify(detail);
      }
      return e.message;
    }
    return e instanceof Error ? e.message : 'Request failed.';
  };

  const loadFinalScheduleValidation = async () => {
    if (!seasonId) return null;
    const quality: any = await apiFetch(`/schedule-management/quality-report?season_id=${seasonId}`, {}, token);
    return quality?.final_validation || null;
  };

  const setManualScheduleBannerFromValidation = (action: string, finalValidation: any) => {
    const status = String(finalValidation?.final_validation_status || '').toUpperCase();
    const qualityStatus = String(finalValidation?.schedule_quality_status || '').toUpperCase();
    const failureCount = Number(finalValidation?.hard_rule_failure_count ?? finalValidation?.final_validation_failure_count ?? 0);
    const diagnosticsFailureCount = Number(finalValidation?.diagnostics_reporting_failure_count || 0);
    const missingCount = Number(finalValidation?.required_games_missing_count || 0);
    if (status === 'COMPLETE' && qualityStatus === 'COMPLETE') {
      setSuccess(`${action} Final validation COMPLETE.`);
      return;
    }
    if (diagnosticsFailureCount > 0 && failureCount === 0) {
      setError(`${action} Schedule validation could not be fully audited: ${diagnosticsFailureCount} diagnostics/reporting issue(s). Review Schedule Quality Report before publishing.`);
      return;
    }
    setError(`${action} Schedule is ${status || qualityStatus || 'not complete'}: ${failureCount} detailed hard-rule failure(s), ${missingCount} required games missing. Review Schedule Quality Report for affected records/scopes.`);
  };


  const load = async () => {
    const opts: any = await apiFetch('/manual-schedule-builder/options', {}, token);
    const statuses: any = await apiFetch('/game-statuses?page_size=200', {}, token);
    setOptions({ ...opts, game_statuses: statuses.items || [] });
    const activeSeason = opts.seasons?.find((s: any) => s.is_active);
    if (!seasonId && activeSeason?.id) setSeasonId(activeSeason.id);
    if (!divisionId && opts.divisions?.length) setDivisionId(opts.divisions[0].id);
    const scheduled: any = await apiFetch('/games?page_size=300', {}, token);
    setGames((scheduled.items || []).filter((game: any) => (game.status_code || game.game_status_code) !== 'UNSCHEDULED'));
  };

  const loadGeneratedSlots = async () => {
    const params = new URLSearchParams();
    if (seasonId) params.set('season_id', seasonId);
    const data: any = await apiFetch(`/generated-game-slots${params.toString() ? `?${params.toString()}` : ''}`, {}, token);
    setGeneratedSlots(Array.isArray(data) ? data : []);
  };

  const loadRecommendations = async () => {
    if (!divisionId || !weekId) return;
    const r: any = await apiFetch('/manual-schedule-builder/recommendations', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId, organization_id: organizationId || null, host_location_id: hostLocationId || null, home_team_id: homeTeamId || null, away_team_id: awayTeamId || null }) }, token);
    setSuggestedMatchups(r.suggested_matchups || []);
    setSuggestedSlots(r.suggested_slots || []);
    setSlots(r.suggested_slots || []);
    setAllWeeklyMatchupsScheduled(Boolean(r.all_available_weekly_matchups_scheduled));
    setNoEligibleTeamMatchups(Boolean(r.no_eligible_team_matchups));
  };

  useEffect(() => { load().catch((e) => setError(extractError(e))); }, []);
  useEffect(() => { loadGeneratedSlots().catch((e) => setError(extractError(e))); }, [seasonId]);
  useEffect(() => { loadRecommendations().catch((e) => setError(extractError(e))); }, [seasonId, weekId, divisionId, organizationId, hostLocationId, homeTeamId, awayTeamId]);

  const compactSelectClass = 'w-full min-w-32 rounded border bg-white px-2 py-1 text-xs text-slate-900';
  const dirtyPendingEdits = useMemo(() => Object.values(pendingGameEdits).filter((pendingEdit: any) => hasEditableGameChanges(pendingEdit)), [pendingGameEdits]);
  const pendingChangedCellCount = useMemo(() => dirtyPendingEdits.reduce((total: number, pendingEdit: any) => {
    const original = pendingEdit.__original || {};
    return total + Object.entries(editableGameSnapshot(pendingEdit)).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify((original as any)[key])).length;
  }, 0), [dirtyPendingEdits]);
  const hasPendingBulkEdits = dirtyPendingEdits.length > 0;
  const pendingChangesLabel = `${pendingChangedCellCount} unsaved ${pendingChangedCellCount === 1 ? 'change' : 'changes'} across ${dirtyPendingEdits.length} ${dirtyPendingEdits.length === 1 ? 'game' : 'games'}`;
  const confirmDiscardBulkEdits = () => !hasPendingBulkEdits || window.confirm('Discard all unsaved schedule edits?');

  useEffect(() => {
    if (!hasPendingBulkEdits) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasPendingBulkEdits]);

  const getPendingEditForGame = (game: any) => pendingGameEdits[game.id] || buildEditableGame(game);
  const isDirtyCell = (pendingEdit: any, fieldName: string) => JSON.stringify(editableGameSnapshot(pendingEdit)[fieldName]) !== JSON.stringify(pendingEdit.__original?.[fieldName]);
  const dirtyCellClass = (pendingEdit: any, fieldName: string) => isDirtyCell(pendingEdit, fieldName) ? ' bg-amber-50 ring-1 ring-inset ring-amber-300' : '';
  const getTeamsForDivision = (divisionIdValue: string) => options.teams.filter((t: any) => t.division_id === divisionIdValue && t.is_active);
  const hostSurfaceType = (hostId: string) => String((options.host_locations || []).find((host: any) => String(host.id) === hostId)?.surface_type || '').toUpperCase().replace(/[\s-]+/g, '_');
  const hostSurfaceIsTurfStadium = (surface: string) => surface === 'TURF_STADIUM' || surface === 'STADIUM_SITE' || (surface.startsWith('TURF') && surface.includes('STADIUM')) || (surface.startsWith('ARTIFICIAL_TURF') && surface.includes('STADIUM'));
  const getFieldOptionsForPendingEdit = (pendingEdit: any) => {
    const byDisplayLabel = new Map<string, any>();
    const selectedHostId = String(pendingEdit?.host_location_id || '');
    const selectedHostIsTurf = hostSurfaceIsTurfStadium(hostSurfaceType(selectedHostId));
    const addSlot = (slot: any, preferCurrent = false) => {
      const id = String(slot.field_instance_id || slot.field_id || '');
      const label = explicitFieldSlotLabel(slot);
      if (!id || !label) return;
      if (selectedHostIsTurf && !TURF_FIELD_SLOT_LABELS.includes(label)) return;
      if (byDisplayLabel.has(label) && !preferCurrent) return;
      byDisplayLabel.set(label, { ...slot, explicit_field_slot_label: label });
    };
    (options.field_instances || []).filter((field: any) => !selectedHostId || String(field.host_location_id || '') === selectedHostId).forEach((slot: any) => addSlot(slot));
    generatedSlots.filter((slot: any) => (!selectedHostId || String(slot.host_location_id || '') === selectedHostId)).forEach((slot: any) => addSlot(slot));
    if (pendingEdit?.field_instance_id && !Array.from(byDisplayLabel.values()).some((slot: any) => String(slot.field_instance_id || slot.field_id) === String(pendingEdit.field_instance_id))) {
      addSlot({ field_instance_id: pendingEdit.field_instance_id, field_id: pendingEdit.field_id, host_location_id: pendingEdit.host_location_id, field_instance_name: pendingEdit.field_instance_name || 'Current field', field_type: pendingEdit.field_type, field_size: pendingEdit.field_size }, true);
    }
    const values = Array.from(byDisplayLabel.values());
    return (selectedHostIsTurf
      ? values.sort((a: any, b: any) => TURF_FIELD_SLOT_LABELS.indexOf(explicitFieldSlotLabel(a)) - TURF_FIELD_SLOT_LABELS.indexOf(explicitFieldSlotLabel(b)))
      : values.sort((a: any, b: any) => explicitFieldSlotLabel(a).localeCompare(explicitFieldSlotLabel(b), undefined, { numeric: true }))
    );
  };
  const isPendingEditValid = (pendingEdit: any) => {
    const teams = getTeamsForDivision(pendingEdit.division_id);
    const fields = getFieldOptionsForPendingEdit(pendingEdit);
    return Boolean(pendingEdit.game_date && seasonDateOptions.includes(pendingEdit.game_date) && pendingEdit.kickoff_time && validStartTimeOptions.includes(pendingEdit.kickoff_time) && pendingEdit.division_id && pendingEdit.home_team_id && pendingEdit.away_team_id && pendingEdit.home_team_id !== pendingEdit.away_team_id && pendingEdit.host_location_id && pendingEdit.field_instance_id && teams.some((team: any) => team.id === pendingEdit.home_team_id) && teams.some((team: any) => team.id === pendingEdit.away_team_id) && fields.some((slot: any) => String(slot.field_instance_id || slot.field_id) === String(pendingEdit.field_instance_id)));
  };
  const hasInvalidPendingEdits = dirtyPendingEdits.some((pendingEdit: any) => !isPendingEditValid(pendingEdit));
  const updatePendingEditForGame = (game: any, patch: Record<string, unknown>) => {
    if (!canBulkInlineEditScheduledGames || !isBulkEditMode) return;
    setPendingGameEdits((current) => {
      const base = current[game.id] || buildEditableGame(game);
      return { ...current, [game.id]: { ...base, ...patch } };
    });
  };
  const updateScheduledGamesFilters = (patch: Partial<ScheduledGamesFilters>) => {
    if (!confirmDiscardBulkEdits()) return;
    setPendingGameEdits({});
    setScheduledGamesFilters((current) => ({ ...current, ...patch }));
  };
  const applyScheduledGameUpdate = (updatedGame: any) => {
    setGames((prev) => prev.map((game: any) => game.id === updatedGame.id ? { ...game, ...updatedGame, game_status_code: updatedGame.status_code } : game));
  };
  const buildBulkPayload = (overrideWarnings: boolean) => ({
    overrideWarnings,
    override_warnings: overrideWarnings,
    changes: dirtyPendingEdits.map((pendingEdit: any) => ({
      game_id: pendingEdit.id,
      gameId: pendingEdit.id,
      season_id: pendingEdit.season_id,
      week_id: pendingEdit.week_id,
      division_id: pendingEdit.division_id,
      home_team_id: pendingEdit.home_team_id,
      away_team_id: pendingEdit.away_team_id,
      host_location_id: pendingEdit.host_location_id,
      field_instance_id: pendingEdit.field_instance_id,
      game_status_id: pendingEdit.game_status_id || null,
      game_date: pendingEdit.game_date,
      kickoff_time: pendingEdit.kickoff_time,
      public_notes: pendingEdit.public_notes || null,
      internal_admin_notes: pendingEdit.internal_admin_notes || null,
      override_warnings: overrideWarnings,
      overrideWarnings,
      score_change_confirmed: overrideWarnings,
      manual_edit_locked: true,
    })),
  });
  const flattenGroupedMessages = (grouped: any): any[] => {
    if (Array.isArray(grouped)) return grouped;
    if (!grouped || typeof grouped !== 'object') return [];
    return Object.values(grouped).flatMap((value: any) => Array.isArray(value) ? value : [value]);
  };
  const summarizeWarnings = (warningsByGame: any) => {
    const counts = new Map<string, number>();
    flattenGroupedMessages(warningsByGame).forEach((warning: any) => {
      const label = String(warning?.code || warning?.error || 'SCHEDULE_WARNING').replaceAll('_', ' ').toLowerCase();
      counts.set(label, (counts.get(label) || 0) + 1);
    });
    return Array.from(counts.entries()).map(([label, count]) => `• ${count} ${label} ${count === 1 ? 'warning' : 'warnings'}`).join('\n') || '• These edits create one or more schedule warnings.';
  };
  const summarizeBulkHardErrors = (errorsByGame: any) => {
    const entries = Object.entries(errorsByGame || {});
    if (!entries.length) return '';
    return entries.map(([gameId, detail]: [string, any]) => {
      const code = String(detail?.error || detail || 'VALIDATION_ERROR').replaceAll('_', ' ').toLowerCase();
      const fields = Array.isArray(detail?.fields) && detail.fields.length ? ` (${detail.fields.join(', ')})` : '';
      return `${gameId}: ${code}${fields}`;
    }).join('; ');
  };
  const saveBulkInlineEdits = async (overrideWarnings = false) => {
    if (!canBulkInlineEditScheduledGames || !hasPendingBulkEdits) return;
    setError('');
    if (hasInvalidPendingEdits) { setError('Select a valid date, time, division, two different division teams, host location, and configured field for every changed row before saving.'); return; }
    try {
      const res: any = await apiFetch('/schedule-management/games/manual-edit/bulk', { method: 'PATCH', body: JSON.stringify(buildBulkPayload(overrideWarnings)) }, token);
      (res.games || []).forEach(applyScheduledGameUpdate);
      setPendingGameEdits({});
      setIsBulkEditMode(false);
      await load(); await loadRecommendations(); setManualScheduleBannerFromValidation(overrideWarnings ? 'Schedule changes saved with warning override.' : 'Schedule changes saved.', await loadFinalScheduleValidation());
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 400) {
        const bulkErrors = (e.details as any)?.detail?.errors;
        if (bulkErrors) { setError(`Unable to save bulk schedule changes: ${summarizeBulkHardErrors(bulkErrors)}`); return; }
      }
      if (e instanceof ApiError && e.status === 409) {
        const warnings = (e.details as any)?.detail?.warnings || {};
        const confirmed = window.confirm(`Manual Override Warnings\n\n${summarizeWarnings(warnings)}\n\nThese edits create schedule warnings and may require manual rebalancing of turf time slots or field configurations. As Scheduling Administrator, you may override and save these changes.\n\nSave Anyway?`);
        if (confirmed) await saveBulkInlineEdits(true);
        return;
      }
      setError(extractError(e));
    }
  };


  return (
    <div className='space-y-4'>
      <h1 className='text-2xl font-bold'>Manual Schedule Builder (Assisted)</h1>
      {error ? <div className='rounded border border-red-200 bg-red-50 p-2 text-red-700'>{error}</div> : null}
      {success ? <div className='rounded border border-emerald-200 bg-emerald-50 p-2 text-emerald-700'>{success}</div> : null}

      <div className='grid gap-2 md:grid-cols-8'>
        <select className='rounded border p-2' value={seasonId} onChange={(e) => { setSeasonId(e.target.value); setWeekId(''); }}><option value=''>Season</option>{options.seasons.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        <select className='rounded border p-2' value={weekId} onChange={(e) => setWeekId(e.target.value)}><option value=''>Week</option>{seasonWeeks.map((w: any) => <option key={w.id} value={w.id}>{getWeekOptionLabel(w)}</option>)}</select>
        <select className='rounded border p-2' value={divisionId} onChange={(e) => setDivisionId(e.target.value)}><option value=''>Division</option>{options.divisions.map((d: any) => <option key={d.id} value={d.id}>{getDivisionLabel(d)}</option>)}</select>
        <select className='rounded border p-2' value={organizationId} onChange={(e) => setOrganizationId(e.target.value)}><option value=''>Organization</option>{options.organizations?.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>
        <select className='rounded border p-2' value={hostLocationId} onChange={(e) => setHostLocationId(e.target.value)}><option value=''>Host Location</option>{options.host_locations.map((h: any) => <option key={h.id} value={h.id}>{h.name}</option>)}</select>
        <select className='rounded border p-2' value={homeTeamId} onChange={(e) => setHomeTeamId(e.target.value)}><option value=''>Home Team</option>{divisionTeams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <select className='rounded border p-2' value={awayTeamId} onChange={(e) => setAwayTeamId(e.target.value)}><option value=''>Away Team</option>{divisionTeams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <button className='rounded bg-blue-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300' disabled={!canSave} onClick={async () => {
          setError(''); setSuccess('');
          try {
            const res: any = await apiFetch('/manual-schedule-builder/assign', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId, home_team_id: homeTeamId, away_team_id: awayTeamId, generated_slot_id: slotId }) }, token);
            await load(); await loadRecommendations(); setSlotId(''); setManualScheduleBannerFromValidation('Game scheduled.', res.final_validation);
          } catch (e: unknown) { setError(extractError(e)); }
        }}>Save Game Assignment</button>
      </div>
      <div className='rounded border p-3'>
        <div className='flex items-center justify-between'>
          <h2 className='text-lg font-semibold'>Auto-Schedule Assistant</h2>
          <button
            className='rounded bg-indigo-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300'
            disabled={!canManageGeneratedGames || !seasonId || !weekId || !divisionId || autoFillLoading}
            onClick={async () => {
              setError('');
              setSuccess('');
              setAutoFillLoading(true);
              try {
                const res: any = await apiFetch('/manual-schedule-builder/auto-fill-preview', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId }) }, token);
                setAutoFillPreview(res.proposals || []);
                setSchedulerDiagnostics(res.diagnostics || null);
                const normalizedSkipped = (res.skipped || []).filter((s: any) => {
                  if ((s.reason || '').includes('Weekly game limit reached') && Number(s.active_games_counted || 0) === 0) return false;
                  return true;
                }).map((s: any) => {
                  if ((s.reason || '').includes('Weekly game limit reached') && Number(s.max_games_allowed || 0) > 0) {
                    return { ...s, reason: `Weekly game limit reached: ${s.max_games_allowed} of ${s.max_games_allowed} games already scheduled.` };
                  }
                  return s;
                });
                setAutoFillSkipped(normalizedSkipped);
              } catch (e: unknown) {
                setError(extractError(e));
              } finally {
                setAutoFillLoading(false);
              }
            }}
          >
            Auto-Fill Selected Division/Week
          </button>
        </div>
        {autoFillPreview.length > 0 ? <div className='mt-3 space-y-3'>
          <div className='overflow-auto rounded border'>
            <table className='min-w-full text-sm'>
              <thead><tr>{['Proposed Matchup', 'Date/Time', 'Host Location', 'Field', 'Reason', 'Score'].map((h) => <th key={h} className='px-2 py-2 text-left'>{h}</th>)}</tr></thead>
              <tbody>
                {autoFillPreview.map((p: any, idx: number) => <tr key={`${p.slot_id}-${idx}`} className='border-t'>
                  <td className='p-2'>{p.proposed_matchup}</td>
                  <td className='p-2'>{formatDisplayDateTime(p.proposed_date, p.proposed_start_time)}</td>
                  <td className='p-2'>{p.host_location}</td>
                  <td className='p-2'>{p.field}</td>
                  <td className='p-2'>{p.reason}</td>
                  <td className='p-2 font-semibold'>{p.score}</td>
                </tr>)}
              </tbody>
            </table>
          </div>
          <div className='flex gap-2'>
            <button className='rounded bg-emerald-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300' disabled={!canManageGeneratedGames} onClick={async () => {
              if (!canManageGeneratedGames) return;
              setError('');
              setSuccess('');
              try {
                const applied: any = await apiFetch('/manual-schedule-builder/auto-fill-apply', { method: 'POST', body: JSON.stringify({ season_id: seasonId, week_id: weekId, division_id: divisionId, proposals: autoFillPreview }) }, token);
                const maxGames = Number(applied.max_games ?? autoFillPreview.length ?? 0);
                const createdCount = Number(applied.created_count ?? applied.created_games ?? 0);
                const finalValidation = applied.final_validation || await loadFinalScheduleValidation();
                setManualScheduleBannerFromValidation(`Applied auto-fill. Created ${createdCount} of ${maxGames} possible games.`, finalValidation);
                setAutoFillSkipped((applied.skipped || []).map((s: any) => ({ reason: s.reason || String(s) })));
                setSchedulerDiagnostics(applied.diagnostics || schedulerDiagnostics);
                setAutoFillPreview([]);
                await load();
                await loadRecommendations();
              } catch (e: unknown) {
                setError(extractError(e));
              }
            }}>Apply Schedule</button>
            <button className='rounded border px-3 py-2' onClick={() => { setAutoFillPreview([]); setAutoFillSkipped([]); }}>Cancel</button>
          </div>
        </div> : null}
        {autoFillSkipped.length > 0 ? <div className='mt-3 rounded border bg-amber-50 p-2 text-sm'>
          <div className='font-semibold'>Skipped teams/matchups</div>
          <ul className='list-inside list-disc'>
            {autoFillSkipped.map((s: any, idx: number) => <li key={idx}>{s.reason || JSON.stringify(s)}</li>)}
          </ul>
        </div> : null}
        {schedulerDiagnostics ? <div className='mt-3 rounded border bg-slate-50 p-3 text-sm'>
          <div className='font-semibold'>Scheduler Diagnostics</div>
          <ul className='mt-1 list-inside list-disc'>
            <li>Teams evaluated: {schedulerDiagnostics.teams_evaluated ?? 0}</li>
            <li>Slots evaluated: {schedulerDiagnostics.slots_evaluated ?? 0}</li>
            <li>Valid matchups found: {schedulerDiagnostics.valid_matchups_found ?? 0}</li>
            <li>Valid slot combinations found: {schedulerDiagnostics.valid_slot_combinations_found ?? 0}</li>
            <li>Rules relaxed: {schedulerDiagnostics.rules_relaxed ?? 0}</li>
            <li>Conflicts avoided: {schedulerDiagnostics.conflicts_avoided ?? 0}</li>
            <li>Final games created: {schedulerDiagnostics.final_games_created ?? 0}</li>
          </ul>
        </div> : null}
      </div>
      <div className='rounded border border-red-200 bg-red-50 p-3'>
        <h2 className='text-lg font-semibold text-red-800'>Administrative Management</h2>
        <p className='mt-1 text-sm text-red-700'>Use this only when you need to reset generated schedules for the selected season.</p>
        <button
          className='mt-3 mr-2 rounded border border-indigo-700 bg-indigo-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300 disabled:border-slate-300'
          disabled={!canManageGeneratedGames || !seasonId}
          onClick={() => {
            if (!canManageGeneratedGames) return;
            setError('');
            setSuccess('');
            setClearExistingBeforeAutoSchedule(false);
            setShowAutoScheduleSeasonModal(true);
          }}
        >
          Auto-Schedule Entire Season
        </button>
        <button
          className='mt-3 rounded border border-red-600 bg-red-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:bg-slate-300 disabled:border-slate-300'
          disabled={!canManageGeneratedGames || !seasonId}
          onClick={() => {
            if (!canManageGeneratedGames) return;
            setError('');
            setSuccess('');
            setClearScheduleInput('');
            setShowClearScheduleModal(true);
          }}
        >
          Clear All Scheduled Games
        </button>
      </div>

      <div className='rounded border p-3'>
        <h2 className='mb-2 text-lg font-semibold'>Suggested Matchups</h2>
        {noEligibleTeamMatchups && suggestedMatchups.length === 0 ? (
          <div className='mb-2 rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-800'>
            No eligible team matchups could be generated.
          </div>
        ) : null}
        {allWeeklyMatchupsScheduled && suggestedMatchups.length === 0 && !noEligibleTeamMatchups ? (
          <div className='mb-2 rounded border border-blue-200 bg-blue-50 p-2 text-sm text-blue-800'>
            All available weekly matchups have been scheduled for this division/week.
          </div>
        ) : null}
        <table className='min-w-full text-sm'><thead><tr>{['Home Team', 'Away Team', 'Reason', 'Score'].map((h) => <th key={h} className='px-2 py-2 text-left font-bold'>{h}</th>)}</tr></thead><tbody>
          {suggestedMatchups.map((m: any, idx: number) => <tr key={`${m.home_team_id}-${m.away_team_id}-${idx}`} className='border-t'><td className='p-2'>{m.home_team_name}</td><td className='p-2'>{m.away_team_name}</td><td className='p-2'>{m.reason}</td><td className='p-2 font-semibold'>{m.score}</td></tr>)}
        </tbody></table>
      </div>

      <div className='overflow-auto rounded border'>
        <table className='min-w-full border-separate border-spacing-y-1 text-sm'><thead><tr>{['Date', 'Host Location', 'Field', 'Field Type', 'Start', 'End', 'Reason', 'Score', 'Recommendation', 'Select'].map((h) => <th key={h} className='px-2 py-2 text-center font-bold'>{h}</th>)}</tr></thead><tbody>
          {slots.map((s: any) => {
            const color = s.indicator === 'green' ? 'bg-emerald-50' : s.indicator === 'yellow' ? 'bg-yellow-50' : s.indicator === 'red' ? 'bg-red-50' : 'bg-white';
            return <tr key={s.slot_id || s.id} className={`align-middle ${slotId === (s.slot_id || s.id) ? 'ring-1 ring-blue-300' : ''} ${color}`}>
              <td className='px-2 py-3 text-center'>{formatDisplayDate(s.slot_date || s.available_date)}</td><td className='px-2 py-3 text-center'>{s.host_location_name}</td><td className='px-2 py-3 text-center'>{s.field_instance_name}</td><td className='px-2 py-3 text-center'>{s.field_type}</td><td className='px-2 py-3 text-center'>{formatDisplayTime(s.start_time)}</td><td className='px-2 py-3 text-center'>{formatDisplayTime(s.end_time)}</td><td className='px-2 py-3 text-center'>{s.reason || '-'}</td><td className='px-2 py-3 text-center font-semibold'>{s.score ?? '-'}</td><td className='px-2 py-3 text-center'>{s.rating || '-'}</td><td className='px-2 py-3 text-center'><button className='rounded border px-2 py-1 text-xs' onClick={() => setSlotId(s.slot_id || s.id)}>Use Recommended Slot</button></td>
            </tr>;
          })}
        </tbody></table>
      </div>
      <div className='rounded border p-3'>
        <div className='mb-3 flex flex-wrap items-center justify-between gap-3'>
          <div>
            <h2 className='text-lg font-semibold'>Scheduled Games</h2>
          </div>
        </div>
        <div className='mb-3 rounded border bg-slate-50 p-3'>
          <div className='grid gap-2 sm:grid-cols-2 lg:grid-cols-6'>
            <label className='flex flex-col gap-1 text-xs font-semibold text-slate-700'>Date
              <select className='rounded border bg-white p-2 text-sm font-normal text-slate-900' value={scheduledGamesFilters.date} onChange={(e) => updateScheduledGamesFilters({ date: e.target.value })}>
                <option value=''>All</option>
                {scheduledGamesFilterOptions.dates.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className='flex flex-col gap-1 text-xs font-semibold text-slate-700'>Time
              <select className='rounded border bg-white p-2 text-sm font-normal text-slate-900' value={scheduledGamesFilters.time} onChange={(e) => updateScheduledGamesFilters({ time: e.target.value })}>
                <option value=''>All</option>
                {scheduledGamesFilterOptions.times.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className='flex flex-col gap-1 text-xs font-semibold text-slate-700'>Division
              <select className='rounded border bg-white p-2 text-sm font-normal text-slate-900' value={scheduledGamesFilters.division} onChange={(e) => updateScheduledGamesFilters({ division: e.target.value })}>
                <option value=''>All</option>
                {scheduledGamesFilterOptions.divisions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className='flex flex-col gap-1 text-xs font-semibold text-slate-700'>Host Location
              <select className='rounded border bg-white p-2 text-sm font-normal text-slate-900' value={scheduledGamesFilters.hostLocation} onChange={(e) => updateScheduledGamesFilters({ hostLocation: e.target.value, field: '' })}>
                <option value=''>All</option>
                {scheduledGamesFilterOptions.hostLocations.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className='flex flex-col gap-1 text-xs font-semibold text-slate-700'>Field
              <select className='rounded border bg-white p-2 text-sm font-normal text-slate-900' value={scheduledGamesFilters.field} onChange={(e) => updateScheduledGamesFilters({ field: e.target.value })}>
                <option value=''>All</option>
                {scheduledGamesFilterOptions.fields.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <div className='flex flex-col justify-end gap-1'>
              <button className='rounded border bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400' disabled={!hasScheduledGamesFilters} onClick={() => updateScheduledGamesFilters(emptyScheduledGamesFilters)}>Clear Filters</button>
            </div>
          </div>
          <div className='mt-2 text-sm text-slate-600'>Showing {filteredGames.length} of {games.length} scheduled games</div>
        </div>
        {canBulkInlineEditScheduledGames ? <div className='mb-3 flex flex-wrap items-center gap-3 rounded border border-blue-100 bg-blue-50 p-3' aria-label='Scheduling Administrator bulk edit toolbar'>
          {!isBulkEditMode ? <>
            <button className='rounded bg-blue-600 px-3 py-2 text-sm text-white' onClick={() => { setError(''); setSuccess(''); setIsBulkEditMode(true); }}>Modify Schedule</button>
            <span className='text-sm text-slate-600'>Enable global inline editing to update multiple scheduled games before saving once.</span>
          </> : <>
            <span className={`text-sm font-semibold ${hasPendingBulkEdits ? 'text-blue-900' : 'text-slate-600'}`}>{hasPendingBulkEdits ? pendingChangesLabel : '0 unsaved changes across 0 games'}</span>
            <button className='rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300' disabled={!hasPendingBulkEdits || hasInvalidPendingEdits} onClick={() => saveBulkInlineEdits(false)}>Save Changes</button>
            <button className='rounded border bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400' disabled={!hasPendingBulkEdits} onClick={() => setPendingGameEdits({})}>Discard Changes</button>
            <button className='rounded border bg-white px-3 py-2 text-sm' onClick={() => { if (!confirmDiscardBulkEdits()) return; setPendingGameEdits({}); setIsBulkEditMode(false); }}>Exit Edit Mode</button>
            {hasInvalidPendingEdits ? <span className='text-sm text-red-700'>Fix invalid changed rows before saving.</span> : null}
          </>}
        </div> : null}
        {games.length > 0 && filteredGames.length === 0 ? <div className='rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800'>No scheduled games match the selected filters.</div> : null}
        <div className='overflow-auto'>
          <table className='min-w-full text-sm'>
            <thead><tr>{['Date', 'Time', 'Division', 'Home Team', 'Away Team', 'Host Location', 'Field', 'Notes', ...(canManageGeneratedGames ? ['Actions'] : [])].map((h) => <th key={h} className='px-2 py-2 text-left'>{h}</th>)}</tr></thead>
            <tbody>
              {filteredGames.map((g: any) => {
                const pendingEdit = getPendingEditForGame(g);
                const isDirtyRow = hasEditableGameChanges(pendingEdit);
                const rowTeams = getTeamsForDivision(pendingEdit.division_id);
                const rowFieldOptions = getFieldOptionsForPendingEdit(pendingEdit);
                const selectedField = rowFieldOptions.find((slot: any) => String(slot.field_instance_id || slot.field_id) === String(pendingEdit.field_instance_id || pendingEdit.field_id || ''));
                const selectedDivision = options.divisions.find((d: any) => d.id === pendingEdit.division_id);
                const selectedFieldType = String(selectedField?.field_size || selectedField?.field_type || '').toUpperCase();
                const divisionDefaultFieldType = String(selectedDivision?.required_field_type || '').toUpperCase();
                const fieldSizeMismatch = Boolean(selectedFieldType && divisionDefaultFieldType && selectedFieldType !== divisionDefaultFieldType);
                const fieldSizeLabel = selectedFieldType ? `Selected field type: ${selectedFieldType}${divisionDefaultFieldType ? ` • Division default field type: ${divisionDefaultFieldType}` : ''}` : (divisionDefaultFieldType ? `Division default field type: ${divisionDefaultFieldType}` : 'Select a field to view field type');
                const editable = canBulkInlineEditScheduledGames && isBulkEditMode;
                return <tr key={g.id} className={`border-t align-top ${isDirtyRow ? 'bg-amber-50/40 outline outline-1 outline-amber-200' : ''}`}>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'game_date')}`}>{editable ? <select className={compactSelectClass} value={pendingEdit.game_date || ''} onChange={(e) => updatePendingEditForGame(g, { game_date: e.target.value })}><option value=''>Date</option>{seasonDateOptions.map((d: any) => <option key={d} value={d}>{formatDisplayDate(d)}</option>)}</select> : formatDisplayDate(g.game_date)}</td>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'kickoff_time')}`}>{editable ? <select className={compactSelectClass} value={pendingEdit.kickoff_time || ''} onChange={(e) => updatePendingEditForGame(g, { kickoff_time: e.target.value })}><option value=''>Time</option>{validStartTimeOptions.map((t: any) => <option key={t} value={t}>{formatDisplayTime(t)}</option>)}</select> : formatDisplayTime(g.kickoff_time)}</td>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'division_id')}`}>{editable ? <select className={compactSelectClass} value={pendingEdit.division_id || ''} onChange={(e) => updatePendingEditForGame(g, { division_id: e.target.value, home_team_id: '', away_team_id: '' })}><option value=''>Division</option>{options.divisions.map((d: any) => <option key={d.id} value={d.id}>{getDivisionLabel(d)}</option>)}</select> : (g.division_name || 'Unknown Division')}</td>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'home_team_id')}`}>{editable ? <select className={compactSelectClass} value={pendingEdit.home_team_id || ''} onChange={(e) => updatePendingEditForGame(g, { home_team_id: e.target.value })}><option value=''>Home Team</option>{rowTeams.map((t: any) => <option key={t.id} value={t.id} disabled={t.id === pendingEdit.away_team_id}>{t.name}</option>)}</select> : (g.home_team_name || 'Unknown Team')}</td>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'away_team_id')}`}>{editable ? <select className={compactSelectClass} value={pendingEdit.away_team_id || ''} onChange={(e) => updatePendingEditForGame(g, { away_team_id: e.target.value })}><option value=''>Away Team</option>{rowTeams.map((t: any) => <option key={t.id} value={t.id} disabled={t.id === pendingEdit.home_team_id}>{t.name}</option>)}</select> : (g.away_team_name || 'Unknown Team')}</td>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'host_location_id')}`}>{editable ? <select className={compactSelectClass} value={pendingEdit.host_location_id || ''} onChange={(e) => updatePendingEditForGame(g, { host_location_id: e.target.value, field_instance_id: '' })}><option value=''>Host Location</option>{options.host_locations.map((h: any) => <option key={h.id} value={h.id}>{h.name}</option>)}</select> : (g.host_location_name || '-')}</td>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'field_instance_id')}`}>{editable ? <div className='space-y-1'><select className={compactSelectClass} value={pendingEdit.field_instance_id || ''} onChange={(e) => { const selected = rowFieldOptions.find((slot: any) => String(slot.field_instance_id || slot.field_id) === e.target.value); updatePendingEditForGame(g, { field_instance_id: e.target.value, field_id: selected?.field_id || pendingEdit.field_id, host_location_id: selected?.host_location_id || pendingEdit.host_location_id }); }}><option value=''>Field</option>{rowFieldOptions.map((s: any) => <option key={`${s.field_instance_id || s.field_id}-${s.slot_id || s.id}`} value={s.field_instance_id || s.field_id}>{s.explicit_field_slot_label || explicitFieldSlotLabel(s)}</option>)}</select><div className={`text-[11px] ${fieldSizeMismatch ? 'text-amber-700' : 'text-slate-500'}`}>{fieldSizeLabel}</div></div> : (explicitFieldSlotLabel(g) || '-')}</td>
                  <td className={`p-2${dirtyCellClass(pendingEdit, 'public_notes')}${dirtyCellClass(pendingEdit, 'internal_admin_notes')}`}>{editable ? <details><summary className='cursor-pointer text-xs text-blue-700 underline'>Edit notes</summary><div className='mt-2 grid min-w-64 gap-2'><textarea className='rounded border p-2 text-xs' value={pendingEdit.public_notes || ''} onChange={(e) => updatePendingEditForGame(g, { public_notes: e.target.value })} placeholder='Public notes' /><textarea className='rounded border p-2 text-xs' value={pendingEdit.internal_admin_notes || ''} onChange={(e) => updatePendingEditForGame(g, { internal_admin_notes: e.target.value })} placeholder='Internal admin notes' /></div></details> : ((g.public_notes || g.internal_admin_notes) ? <details><summary className='cursor-pointer text-xs text-blue-700 underline'>View notes</summary><div className='mt-1 min-w-48 space-y-1 text-xs text-slate-700'>{g.public_notes ? <p><span className='font-semibold'>Public:</span> {g.public_notes}</p> : null}{g.internal_admin_notes ? <p><span className='font-semibold'>Internal:</span> {g.internal_admin_notes}</p> : null}</div></details> : <span className='text-slate-400'>-</span>)}</td>
                  {canManageGeneratedGames ? <td className='p-2'><div className='flex flex-wrap gap-2'>
                    {isBulkEditMode ? <>
                      <span className='rounded border border-blue-100 bg-blue-50 px-2 py-1 text-xs text-blue-800'>Inline edit mode</span>
                      {isDirtyRow && canBulkInlineEditScheduledGames ? <button className='rounded border px-2 py-1 text-xs' onClick={() => setPendingGameEdits((current) => { const next = { ...current }; delete next[g.id]; return next; })}>Reset Row</button> : null}
                    </> : <>
                      <button className='rounded border px-2 py-1 text-xs' onClick={() => { if (!confirmDiscardBulkEdits()) return; setPendingGameEdits({}); setMoveGame(g); }}>Move</button>
                      <button className='rounded border border-red-300 px-2 py-1 text-xs text-red-700' onClick={async () => {
                        if (!confirmDiscardBulkEdits()) return;
                        if (!window.confirm('Remove this scheduled game?')) return;
                        setError('');
                        setPendingGameEdits({});
                        setAutoFillSkipped([]);
                        setAutoFillPreview([]);
                        try {
                          setGames((prev) => prev.filter((game: any) => game.id !== g.id));
                          await apiFetch(`/schedule-management/games/${g.id}/unschedule`, { method: 'PATCH' }, token);
                          await load();
                          await loadRecommendations();
                          setManualScheduleBannerFromValidation('Game unscheduled.', await loadFinalScheduleValidation());
                        }
                        catch (e: unknown) {
                          await load();
                          await loadRecommendations();
                          setError(extractError(e));
                        }
                      }}>Delete / Unschedule</button>
                    </>}
                  </div></td> : null}
                </tr>;
              })}
            </tbody>
          </table>
        </div>
      </div>
      {moveGame ? <div className='rounded border bg-slate-50 p-3'>
        <h3 className='mb-2 font-semibold'>Move Game</h3>
        <select className='rounded border p-2' value={slotId} onChange={(e) => setSlotId(e.target.value)}>
          <option value=''>Select OPEN slot</option>
          {slots.map((s: any) => <option key={s.slot_id || s.id} value={s.slot_id || s.id}>{formatDisplayDateTime(s.slot_date || s.available_date, s.start_time)} - {s.host_location_name} ({s.field_type})</option>)}
        </select>
        <div className='mt-2 flex gap-2'>
          <button className='rounded bg-blue-600 px-3 py-2 text-white' onClick={async () => {
            if (!slotId) return;
            setError('');
            try { await apiFetch(`/schedule-management/games/${moveGame.id}/move`, { method: 'PATCH', body: JSON.stringify({ generated_slot_id: slotId }) }, token); setMoveGame(null); setSlotId(''); await load(); await loadRecommendations(); setManualScheduleBannerFromValidation('Game moved.', await loadFinalScheduleValidation()); }
            catch (e: unknown) { setError(extractError(e)); }
          }}>Save Move</button>
          <button className='rounded border px-3 py-2' onClick={() => { setMoveGame(null); setSlotId(''); }}>Cancel</button>
        </div>
      </div> : null}
      {showClearScheduleModal ? <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4'>
        <div className='w-full max-w-xl rounded-lg bg-white p-4 shadow-xl'>
          <h3 className='text-lg font-semibold text-red-700'>Confirm Clear Scheduled Games</h3>
          <p className='mt-2 text-sm text-slate-700'>
            This will permanently remove all scheduled games for the selected season. This action cannot be undone.
          </p>
          <p className='mt-3 text-sm font-medium'>Type <span className='font-bold'>CLEAR SCHEDULE</span> to continue.</p>
          <input
            className='mt-2 w-full rounded border p-2'
            value={clearScheduleInput}
            onChange={(e) => setClearScheduleInput(e.target.value)}
            placeholder='CLEAR SCHEDULE'
          />
          <div className='mt-4 flex justify-end gap-2'>
            <button
              className='rounded border px-3 py-2'
              disabled={clearScheduleLoading}
              onClick={() => {
                setShowClearScheduleModal(false);
                setClearScheduleInput('');
              }}
            >
              Cancel
            </button>
            <button
              className='rounded border border-red-600 bg-red-600 px-3 py-2 text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300'
              disabled={clearScheduleLoading || clearScheduleInput !== 'CLEAR SCHEDULE'}
              onClick={async () => {
                if (!seasonId) return;
                setError('');
                setSuccess('');
                setClearScheduleLoading(true);
                try {
                  await apiFetch(`/manual-schedule-builder/scheduled-games?season_id=${seasonId}`, { method: 'DELETE' }, token);
                  setShowClearScheduleModal(false);
                  setClearScheduleInput('');
                  await load();
                  await loadRecommendations();
                  setAutoFillPreview([]);
                  setAutoFillSkipped([]);
                  setSuccess('All scheduled games have been cleared.');
                } catch (e: unknown) {
                  setError(extractError(e));
                } finally {
                  setClearScheduleLoading(false);
                }
              }}
            >
              {clearScheduleLoading ? 'Clearing...' : 'Confirm Clear Schedule'}
            </button>
          </div>
        </div>
      </div> : null}
      {showAutoScheduleSeasonModal ? <div className='fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4'>
        <div className='w-full max-w-xl rounded-lg bg-white p-4 shadow-xl'>
          <h3 className='text-lg font-semibold text-indigo-700'>Confirm Full-Season Auto-Schedule</h3>
          <p className='mt-2 text-sm text-slate-700'>
            This will attempt to auto-schedule all unscheduled games for the selected season across all divisions and weeks.
          </p>
          <label className='mt-4 flex items-center gap-2 text-sm'>
            <input type='checkbox' checked={clearExistingBeforeAutoSchedule} onChange={(e) => setClearExistingBeforeAutoSchedule(e.target.checked)} />
            Clear existing scheduled games before running
          </label>
          <label className='mt-2 flex items-center gap-2 text-sm'>
            <input type='checkbox' checked={autoScheduleDryRun} onChange={(e) => setAutoScheduleDryRun(e.target.checked)} />
            Dry run (preview only, do not save)
          </label>
          <div className='mt-4 flex justify-end gap-2'>
            <button className='rounded border px-3 py-2' disabled={autoScheduleSeasonLoading} onClick={() => setShowAutoScheduleSeasonModal(false)}>Cancel</button>
            <button
              className='rounded border border-indigo-700 bg-indigo-700 px-3 py-2 text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-300'
              disabled={autoScheduleSeasonLoading || !seasonId}
              onClick={async () => {
                setError('');
                setSuccess('');
                // Keep the previous diagnostics visible while the next run is in progress.
                // They will be replaced by the HTTP 200 response even when the response status is warning/incomplete.
                if (!autoScheduleDryRun && games.some((game: any) => game.is_manual_edit) && !window.confirm('Regenerating may overwrite manual schedule edits. Continue?')) return;
                setAutoScheduleSeasonLoading(true);
                try {
                  const res: any = await apiFetch('/manual-schedule-builder/auto-schedule-season', { method: 'POST', body: JSON.stringify({ season_id: seasonId, clear_existing: clearExistingBeforeAutoSchedule, dry_run: autoScheduleDryRun }) }, token);
                  setShowAutoScheduleSeasonModal(false);
                  await load();
                  await loadRecommendations();
                  setAutoScheduleDiagnostics(summarizeAutoScheduleDiagnostics(res));
                  const finalValidation = res.final_validation || res.auto_schedule_diagnostics?.final_validation || {};
                  const finalStatus = String(finalValidation.final_validation_status || res.final_validation_status || res.status || '').toUpperCase();
                  const rootCauses = (res.root_cause_categories || res.auto_schedule_diagnostics?.root_cause_categories || []).join(', ');
                  const baseMessage = res.message || 'Auto-schedule completed.';
                  if (res.dry_run && finalStatus === 'COMPLETE') {
                    setSuccess(res.message || `Dry run completed: ${Number(res.preview_games_count || 0)} games would be scheduled. No games were saved.`);
                  } else if (finalStatus === 'COMPLETE') {
                    setSuccess(`${baseMessage} ${Number(res.committed_games_count ?? res.total_games_created ?? 0)} games scheduled. Final validation COMPLETE.`);
                  } else {
                    const failureCount = Number(finalValidation.hard_rule_failure_count ?? finalValidation.final_validation_failure_count ?? res.final_validation_failure_count ?? 0);
                    const diagnosticsFailureCount = Number(finalValidation.diagnostics_reporting_failure_count || 0);
                    const missing = Number(finalValidation.required_games_missing_count || 0);
                    if (diagnosticsFailureCount > 0 && failureCount === 0) {
                      setError(`${baseMessage} Schedule validation could not be fully audited; ${diagnosticsFailureCount} diagnostics/reporting issue(s). Review Schedule Quality Report.${rootCauses ? ` Root causes: ${rootCauses}.` : ''}`);
                    } else {
                      setError(`${baseMessage} Final status ${finalStatus || 'UNKNOWN'}; ${failureCount} detailed hard-rule failure(s), ${missing} required games missing.${rootCauses ? ` Root causes: ${rootCauses}.` : ''}`);
                    }
                  }
                } catch (e: unknown) {
                  setError(`Auto-schedule failed: ${extractError(e)}`);
                } finally {
                  setAutoScheduleSeasonLoading(false);
                }
              }}
            >
              {autoScheduleSeasonLoading ? 'Running...' : 'Run Auto-Schedule'}
            </button>
          </div>
        </div>
      </div> : null}
      {autoScheduleDiagnostics ? <details className='rounded border border-slate-300 bg-slate-50 p-3'>
        <summary className='cursor-pointer font-semibold text-slate-800'>Scheduling Diagnostics</summary>
        <div className='mt-3 space-y-4 text-sm'>
          <section className='rounded border border-slate-200 bg-white p-3'>
            <div className='flex flex-wrap items-start justify-between gap-3'>
              <div>
                <div><span className='font-semibold'>Status:</span> {autoScheduleDiagnostics.status} — {autoScheduleDiagnostics.message}</div>
                <div><span className='font-semibold'>Final validation status:</span> {autoScheduleDiagnostics.finalValidationStatus}</div>
                <div><span className='font-semibold'>Schedule quality status:</span> {autoScheduleDiagnostics.scheduleQualityStatus}</div>
                <div><span className='font-semibold'>Diagnostics status:</span> {autoScheduleDiagnostics.diagnosticsStatus}{autoScheduleDiagnostics.diagnosticsError ? ` — ${autoScheduleDiagnostics.diagnosticsError}` : ''}</div>
                <div><span className='font-semibold'>Root causes:</span> {autoScheduleDiagnostics.rootCauses.join(', ')}</div>
                <div><span className='font-semibold'>Dry run:</span> {autoScheduleDiagnostics.dryRun ? 'Yes' : 'No'}</div>
              </div>
              {autoScheduleDiagnostics.downloadUrl ? <a className='rounded border border-indigo-700 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-50' href={autoScheduleDiagnostics.downloadUrl} download={autoScheduleDiagnostics.downloadFilename}>Download full diagnostics JSON</a> : null}
            </div>
            <div className='mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3'>
              <div>Games committed: <span className='font-semibold'>{autoScheduleDiagnostics.gamesCommitted}</span></div>
              <div>Preview games: <span className='font-semibold'>{autoScheduleDiagnostics.previewGames}</span></div>
              <div>Required games missing: <span className='font-semibold'>{autoScheduleDiagnostics.requiredGamesMissing}</span></div>
              <div>Final validation failures: <span className='font-semibold'>{autoScheduleDiagnostics.validationFailures}</span></div>
              <div>Team time conflicts: <span className='font-semibold'>{autoScheduleDiagnostics.teamTimeConflicts}</span></div>
              <div>Field time conflicts: <span className='font-semibold'>{autoScheduleDiagnostics.fieldTimeConflicts}</span></div>
              <div>Back-to-back doubleheader failures: <span className='font-semibold'>{autoScheduleDiagnostics.doubleheaderBackToBackFailures}</span></div>
              <div>Host owner as away games: <span className='font-semibold'>{autoScheduleDiagnostics.hostOwnerAsAwayGames}</span></div>
              <div>True home-host rule passed: <span className='font-semibold'>{autoScheduleDiagnostics.trueHomeHostHardRulePassed}</span></div>
              <div>Total home-host violations: <span className='font-semibold'>{autoScheduleDiagnostics.totalHomeHostViolations}</span></div>
              <div>Total home-host exceptions: <span className='font-semibold'>{autoScheduleDiagnostics.totalHomeHostExceptions}</span></div>
              <div>Overflow locations used: <span className='font-semibold'>{autoScheduleDiagnostics.overflowLocationsUsed}</span></div>
              <div>Latest start time: <span className='font-semibold'>{autoScheduleDiagnostics.latestStartTime}</span></div>
              <div>Active time window: <span className='font-semibold'>{autoScheduleDiagnostics.activeTimeWindow}</span></div>
              <div>Pull-forward started: <span className='font-semibold'>{autoScheduleDiagnostics.pullForwardStarted}</span></div>
              <div>Pull-forward completed: <span className='font-semibold'>{autoScheduleDiagnostics.pullForwardCompleted}</span></div>
              <div>Games moved earlier: <span className='font-semibold'>{autoScheduleDiagnostics.gamesMovedEarlier}</span></div>
            </div>
          </section>

          <section className='grid gap-3 lg:grid-cols-2'>
            <div className='rounded border border-slate-200 bg-white p-3'>
              <h3 className='font-semibold'>True Home-Host Diagnostics</h3>
              <dl className='mt-2 grid grid-cols-2 gap-2'>
                {Object.entries(autoScheduleDiagnostics.trueHomeHost).map(([label, count]) => <div key={label}><dt className='text-slate-600'>{label.replaceAll('_', ' ')}</dt><dd className='font-semibold'>{String(count)}</dd></div>)}
              </dl>
            </div>
            <div className='rounded border border-slate-200 bg-white p-3'>
              <h3 className='font-semibold'>Pull-Forward Diagnostics</h3>
              <dl className='mt-2 grid grid-cols-2 gap-2'>
                {Object.entries(autoScheduleDiagnostics.pullForward).map(([label, count]) => <div key={label}><dt className='text-slate-600'>{label.replaceAll('_', ' ')}</dt><dd className='font-semibold'>{String(count)}</dd></div>)}
              </dl>
            </div>
            <div className='rounded border border-slate-200 bg-white p-3'>
              <h3 className='font-semibold'>Rejection Diagnostics</h3>
              {Object.keys(autoScheduleDiagnostics.rejectionReasons).length ? <ul className='mt-2 list-inside list-disc'>{Object.entries(autoScheduleDiagnostics.rejectionReasons).map(([reason, count]) => <li key={reason}>{reason}: {String(count)}</li>)}</ul> : <p className='mt-2 text-slate-700'>No rejection counts returned.</p>}
            </div>
          </section>

          <section className='rounded border border-slate-200 bg-white p-3'>
            <h3 className='font-semibold'>Validation and placement rejection counts</h3>
            <div className='mt-2 grid gap-3 lg:grid-cols-2'>
              <div>
                <div className='font-medium'>Skipped attempts by reason</div>
                {Object.keys(autoScheduleDiagnostics.skippedAttemptsByReason).length ? <ul className='mt-1 list-inside list-disc'>{Object.entries(autoScheduleDiagnostics.skippedAttemptsByReason).map(([reason, count]) => <li key={reason}>{reason}: {String(count)}</li>)}</ul> : <p className='mt-1 text-slate-700'>None returned.</p>}
              </div>
              <div>
                <div className='font-medium'>Failed validation reasons</div>
                {Object.keys(autoScheduleDiagnostics.failedValidationReasons).length ? <ul className='mt-1 list-inside list-disc'>{Object.entries(autoScheduleDiagnostics.failedValidationReasons).map(([reason, count]) => <li key={reason}>{reason}: {String(count)}</li>)}</ul> : <p className='mt-1 text-slate-700'>None returned.</p>}
              </div>
            </div>
          </section>

          <details className='rounded border border-slate-200 bg-white p-2'>
            <summary className='cursor-pointer font-semibold'>Safe compact diagnostics preview</summary>
            <p className='mt-2 text-xs text-slate-600'>The full diagnostics payload is not rendered in the page to prevent browser crashes. Download the JSON file for complete details.</p>
            <pre className='mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-xs'>{autoScheduleDiagnostics.preview}</pre>
          </details>
        </div>
      </details> : null}
    </div>
  );
}
