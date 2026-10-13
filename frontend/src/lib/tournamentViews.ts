export type TournamentSummary = { id: string; name: string; season_id?: string };
export type TournamentView<T extends TournamentSummary> = { id: string; name: string; tournaments: T[] };

// Group only records belonging to the same season, never unrelated events by name alone.
export function tournamentViews<T extends TournamentSummary>(tournaments: T[]): TournamentView<T>[] {
  const groups = new Map<string, T[]>();
  for (const tournament of tournaments) {
    const key = tournament.season_id ? `season:${tournament.season_id}` : tournament.id;
    groups.set(key, [...(groups.get(key) || []), tournament]);
  }
  return Array.from(groups, ([id, members]) => {
    const years = new Set(members.flatMap(t => t.name.match(/\b20\d{2}\b/g) || []));
    const name = members.length === 1 ? members[0].name : years.size === 1 ? `${Array.from(years)[0]} Tournament View` : 'Combined Tournament View';
    return { id, name, tournaments: members };
  });
}
