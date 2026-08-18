export type PublicScoreGame = {
  date: string;
  division_id: string;
  home_organization_id?: string;
  away_organization_id?: string;
  is_official: boolean;
};

export type PublicScoreFilters = {
  community: string;
  date: string;
  division: string;
};

export const filterPublicScores = <T extends PublicScoreGame>(games: T[], filters: PublicScoreFilters): T[] =>
  games.filter(game => game.is_official
    && (!filters.community || game.home_organization_id === filters.community || game.away_organization_id === filters.community)
    && (!filters.date || game.date === filters.date)
    && (!filters.division || game.division_id === filters.division));

/** Formats an API civil game date without allowing the browser timezone to shift it. */
export const formatGameDateOption = (value: string, options: Intl.DateTimeFormatOptions = {
  weekday: 'long', month: 'short', day: 'numeric', year: 'numeric',
}): string => {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return value;
  const [, year, month, day] = match;
  return new Intl.DateTimeFormat('en-US', { ...options, timeZone: 'UTC' })
    .format(new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))));
};
