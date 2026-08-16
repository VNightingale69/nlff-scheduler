'use client';

import CommunityLogo from '@/components/CommunityLogo';
import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

export type HostingViewGame = {
  id?: string;
  date: string;
  time: string;
  hostLocation: string;
  physicalArea: string;
  fieldLane: string;
  fieldType?: string | null;
  division: string;
  homeTeam: string;
  awayTeam: string;
  homeLogoUrl?: string | null;
  homeLogoAlt?: string | null;
  awayLogoUrl?: string | null;
  awayLogoAlt?: string | null;
};

const laneType = (game: HostingViewGame) => (game.fieldType || game.fieldLane || '').toUpperCase();
const tint = (game: HostingViewGame) => laneType(game).includes('SMALL') ? 'bg-emerald-50' : laneType(game).includes('MEDIUM') ? 'bg-sky-50' : laneType(game).includes('LARGE') ? 'bg-rose-50' : 'bg-slate-50';
const key = (game: HostingViewGame) => `${game.physicalArea} · ${game.fieldLane}`;

function GameCard({ game }: { game: HostingViewGame }) {
  return <article className={`hosting-game-cell rounded border border-slate-200 p-2 ${tint(game)}`}>
    <span className='inline-block rounded bg-slate-700 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white'>{game.division}</span>
    <div className='mt-2 flex items-center gap-2 font-semibold'><CommunityLogo src={game.homeLogoUrl} name={game.homeTeam} altText={game.homeLogoAlt} size={22} /><span>{game.homeTeam}</span></div>
    <div className='pl-7 text-[11px] font-semibold uppercase text-slate-500'>vs</div>
    <div className='flex items-center gap-2 font-semibold'><CommunityLogo src={game.awayLogoUrl} name={game.awayTeam} altText={game.awayLogoAlt} size={22} /><span>{game.awayTeam}</span></div>
    <div className='mt-2 border-t border-slate-200 pt-1 text-xs font-bold text-slate-600'>{game.fieldLane}</div>
  </article>;
}

/** Read-only host report. Its caller supplies either saved draft games or public snapshot games. */
export default function HostingView({ games, mode = 'published' }: { games: HostingViewGame[]; mode?: 'published' | 'unpublished' }) {
  const dates = Array.from(new Set(games.map((game) => game.date))).sort();
  return <div className={`hosting-view ${mode === 'unpublished' ? 'unpublished-hosting-view' : ''} space-y-8`}>
    {mode === 'unpublished' && <div className='unpublished-banner rounded border-2 border-amber-400 bg-amber-50 p-3 text-amber-950'><strong className='block uppercase tracking-wide'>Pre-published schedule</strong><span className='text-sm'>Unpublished schedule preview — not visible to the public. Read only and subject to change.</span></div>}
    {dates.map((date) => {
      const dateGames = games.filter((game) => game.date === date);
      const hosts = Array.from(new Set(dateGames.map((game) => game.hostLocation || 'Host Location Unassigned'))).sort();
      return <section key={date} className='hosting-date-section space-y-6'>
        {hosts.map((host) => {
          const hostGames = dateGames.filter((game) => (game.hostLocation || 'Host Location Unassigned') === host);
          const times = Array.from(new Set(hostGames.map((game) => game.time))).sort();
          const lanes = Array.from(new Map(hostGames.map((game) => [key(game), { key: key(game), area: game.physicalArea, lane: game.fieldLane }])).values());
          return <section key={host} className='hosting-location-section break-inside-avoid-page rounded-lg border bg-white shadow-sm'>
            <header className='hosting-location-heading border-b bg-slate-800 px-4 py-3 text-white'><h2 className='text-lg font-extrabold'>{host}</h2><p className='text-sm font-medium text-slate-200'>{formatDisplayDate(date)}</p></header>
            <div className='hosting-grid-scroll overflow-x-auto'>
              <table className='hosting-grid w-full border-collapse text-sm' style={{ minWidth: `${Math.max(760, 120 + lanes.length * 210)}px` }}>
                <thead><tr><th className='hosting-time-cell sticky left-0 z-20 w-[120px] border-b border-r bg-slate-100 p-3 text-left'>Time</th>{lanes.map((lane) => <th key={lane.key} className='min-w-[210px] border-b border-r bg-slate-100 p-3 text-left'><span className='block font-bold'>{lane.area}</span><span className='text-xs text-slate-600'>{lane.lane}</span></th>)}</tr></thead>
                <tbody>{times.map((time) => <tr key={time}><th className='hosting-time-cell sticky left-0 z-10 border-b border-r bg-white p-3 text-left align-top font-bold'>{formatDisplayTime(time)}</th>{lanes.map((lane) => { const matches = hostGames.filter((game) => game.time === time && key(game) === lane.key); return <td key={lane.key} className='border-b border-r p-2 align-top'>{matches.map((game, index) => <GameCard key={game.id || `${lane.key}-${index}`} game={game} />)}{!matches.length && <span className='text-slate-300'>—</span>}</td>; })}</tr>)}</tbody>
              </table>
            </div>
            <div className='hosting-mobile-list hidden p-3'>{times.map((time) => <section key={time} className='mb-5'><h3 className='mb-2 border-b pb-1 text-lg font-extrabold'>{formatDisplayTime(time)}</h3><div className='space-y-2'>{hostGames.filter((game) => game.time === time).map((game, index) => <div key={game.id || `${key(game)}-${index}`}><div className='mb-1 text-xs font-bold text-slate-600'>{game.physicalArea} · {game.fieldLane}</div><GameCard game={game} /></div>)}</div></section>)}</div>
          </section>;
        })}
      </section>;
    })}
    {!games.length && <p className='rounded border bg-white p-4 text-slate-600'>No saved games match the selected week, date, or host location.</p>}
  </div>;
}
