export function scheduleSelection(weekId?: string) {
  const tournament = Boolean(weekId?.startsWith('tournament:'));
  return {
    includeRegular: !tournament,
    includeTournament: tournament || !weekId,
    tournamentSeasonId: tournament ? weekId!.slice('tournament:'.length) : undefined,
  };
}

export function mergeScheduleOptions(regular: Record<string, any[]>, tournament: Record<string, any[]>) {
  return Object.fromEntries(['host_locations', 'organizations', 'divisions', 'weeks', 'teams'].map(key => [key,
    Array.from(new Map([...(regular[key] || []), ...(tournament[key] || [])].map(item => [item.id, item])).values()),
  ]));
}
