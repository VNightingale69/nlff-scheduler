import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

export type TournamentBracketGame = {
  id: string;
  round_name: string;
  round_number: number;
  game_number: number;
  team_1_placeholder: string;
  team_2_placeholder: string;
  team_1_name?: string | null;
  team_2_name?: string | null;
  team_1_seed?: number | null;
  team_2_seed?: number | null;
  team_1_auto_advanced?: boolean;
  team_2_auto_advanced?: boolean;
  date?: string | null;
  time?: string | null;
  host_location_name?: string | null;
  field_name?: string | null;
  status: string;
  score_status: string;
  is_published?: boolean;
  home_score?: number | string | null;
  away_score?: number | string | null;
  winner_team_id?: string | null;
  winner_team_name?: string | null;
  team_1_id?: string | null;
  team_2_id?: string | null;
  needs_review?: boolean;
};

export type TournamentBracketRound = {
  round_number: number;
  round_name: string;
  games: TournamentBracketGame[];
};

export type TournamentBracketDivision = {
  id: string;
  division_name: string;
  division_group: string;
  rounds?: TournamentBracketRound[];
  games?: TournamentBracketGame[];
};

type Props = {
  divisions: TournamentBracketDivision[];
  publicView?: boolean;
};

const statusLabels: Record<string, string> = {
  READY: 'Ready',
  WAITING_FOR_TEAMS: 'Waiting for Teams',
  SCORE_SUBMITTED: 'Score Submitted',
  APPROVED: 'Score Approved',
  PUBLISHED: 'Official Final',
  SCORE_PUBLISHED: 'Official Final',
  COMPLETED: 'Completed',
  ADVANCED: 'Winner Advanced',
  NEEDS_REVIEW: 'Needs Review',
  MISSING: 'Not Scored',
  UNPUBLISHED: 'Unpublished',
};

function displayStatus(game: TournamentBracketGame, publicView?: boolean) {
  if (publicView) return game.status || (game.is_published ? 'Official Final' : 'Scheduled');
  if (game.needs_review) return 'Needs Review';
  return statusLabels[game.status] || statusLabels[game.score_status] || game.status || 'Waiting for Teams';
}

function statusClass(game: TournamentBracketGame, publicView?: boolean) {
  const label = displayStatus(game, publicView).toLowerCase();
  if (label.includes('review') || label.includes('pending update')) return 'border-amber-300 bg-amber-50 text-amber-900';
  if (label.includes('official') || label.includes('completed') || label.includes('advanced')) return 'border-emerald-300 bg-emerald-50 text-emerald-900';
  if (label.includes('submitted') || label.includes('approved')) return 'border-blue-300 bg-blue-50 text-blue-900';
  if (label.includes('waiting')) return 'border-slate-300 bg-slate-50 text-slate-700';
  return 'border-slate-300 bg-white text-slate-800';
}

function formatSeed(seed?: number | null) {
  return seed ? `Seed ${seed}` : 'Seed TBD';
}

function TeamRow({ game, slot }: { game: TournamentBracketGame; slot: 1 | 2 }) {
  const teamId = slot === 1 ? game.team_1_id : game.team_2_id;
  const name = slot === 1 ? game.team_1_name || game.team_1_placeholder : game.team_2_name || game.team_2_placeholder;
  const seed = slot === 1 ? game.team_1_seed : game.team_2_seed;
  const score = slot === 1 ? game.home_score : game.away_score;
  const autoAdvanced = slot === 1 ? game.team_1_auto_advanced : game.team_2_auto_advanced;
  const isWinner = Boolean(game.winner_team_id && teamId && game.winner_team_id === teamId);

  return (
    <div className={`rounded border p-2 ${isWinner ? 'border-emerald-400 bg-emerald-50 font-semibold' : 'border-slate-200 bg-white'}`}>
      <div className='flex items-start justify-between gap-2'>
        <div>
          <div className='text-[11px] uppercase tracking-wide text-slate-500'>{formatSeed(seed)}</div>
          <div>{name || 'TBD'}</div>
          {autoAdvanced && <div className='mt-1 inline-flex rounded bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-800'>Bye / Auto-Advance</div>}
        </div>
        <div className='min-w-8 text-right text-sm font-semibold'>{score ?? '—'}</div>
      </div>
    </div>
  );
}

function roundsForDivision(division: TournamentBracketDivision): TournamentBracketRound[] {
  if (division.rounds?.length) return division.rounds;
  const grouped = new Map<number, TournamentBracketGame[]>();
  (division.games || []).forEach((game) => grouped.set(game.round_number, [...(grouped.get(game.round_number) || []), game]));
  return Array.from(grouped.entries()).sort(([a], [b]) => a - b).map(([round_number, games]) => ({
    round_number,
    round_name: games[0]?.round_name || `Round ${round_number}`,
    games: games.sort((a, b) => a.game_number - b.game_number),
  }));
}

export default function TournamentBracket({ divisions, publicView = false }: Props) {
  if (!divisions.length) return <div className='rounded border p-4 text-sm text-slate-600'>No tournament bracket games are available.</div>;

  return (
    <div className='space-y-8'>
      <div className='flex flex-wrap gap-2 text-xs'>
        {['Ready', 'Waiting for Teams', 'Score Submitted', 'Official Final', publicView ? 'Pending Update' : 'Needs Review'].map((label) => (
          <span key={label} className='rounded-full border bg-white px-2 py-1 text-slate-700'>{label}</span>
        ))}
      </div>
      {divisions.map((division) => {
        const rounds = roundsForDivision(division);
        return (
          <section key={division.id} id={`division-${division.id}`} className='space-y-3'>
            <div>
              <h3 className='text-lg font-semibold'>{division.division_group} {division.division_name}</h3>
              <p className='text-xs text-slate-500'>Bracket source: saved tournament game records and published tournament score advancement.</p>
            </div>
            <div className='overflow-x-auto pb-2'>
              <div className='grid min-w-max auto-cols-[19rem] grid-flow-col gap-4'>
                {rounds.map((round) => (
                  <div key={round.round_number} className='space-y-3'>
                    <div className='sticky left-0 rounded bg-slate-900 px-3 py-2 text-sm font-semibold text-white'>{round.round_name}</div>
                    <div className='space-y-4'>
                      {round.games.map((game) => (
                        <article key={game.id} className={`relative rounded-lg border p-3 shadow-sm ${statusClass(game, publicView)} after:absolute after:left-full after:top-1/2 after:hidden after:h-px after:w-4 after:bg-slate-300 md:after:block`}>
                          <div className='mb-2 flex items-start justify-between gap-2'>
                            <div>
                              <div className='text-xs font-semibold uppercase tracking-wide text-slate-500'>{game.round_name}</div>
                              <div className='font-semibold'>Game {game.game_number}</div>
                            </div>
                            <span className='rounded-full border bg-white/80 px-2 py-1 text-[11px]'>{displayStatus(game, publicView)}</span>
                          </div>
                          <div className='space-y-2'>
                            <TeamRow game={game} slot={1} />
                            <TeamRow game={game} slot={2} />
                          </div>
                          <dl className='mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-600'>
                            <dt className='font-medium'>Date</dt><dd>{formatDisplayDate(game.date || '') || '—'}</dd>
                            <dt className='font-medium'>Time</dt><dd>{formatDisplayTime(game.time || '') || '—'}</dd>
                            <dt className='font-medium'>Host</dt><dd>{game.host_location_name || '—'}</dd>
                            <dt className='font-medium'>Field</dt><dd>{game.field_name || '—'}</dd>
                            <dt className='font-medium'>Winner</dt><dd>{game.winner_team_name || '—'}</dd>
                          </dl>
                        </article>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        );
      })}
    </div>
  );
}
