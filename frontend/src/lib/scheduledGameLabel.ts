export type ScheduledGameLabelSource = {
  scheduled_game_display_name?: string | null;
  home_team_name?: string | null;
  away_team_name?: string | null;
  scheduled_game_id?: string | null;
};

/** Formats the same full team names used elsewhere in schedule administration. */
export function formatScheduledGame(homeTeam?: string | null, awayTeam?: string | null): string | null {
  const home = homeTeam?.trim();
  const away = awayTeam?.trim();
  return home && away ? `${home} vs ${away}` : null;
}

export function getScheduledGameLabel(issue: ScheduledGameLabelSource): string {
  return issue.scheduled_game_display_name
    || formatScheduledGame(issue.home_team_name, issue.away_team_name)
    || (issue.scheduled_game_id ? 'Scheduled game' : 'Schedule-level check');
}
