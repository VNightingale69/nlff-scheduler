import CommunityLogo from '@/components/CommunityLogo';

export type StandingsTableRow = {
  rank: number;
  team_id?: string;
  team_name: string;
  community_name?: string;
  organization_name?: string;
  community_logo_url?: string | null;
  community_logo_alt_text?: string | null;
  wins: number;
  losses: number;
};

export default function StandingsTable({ rows, divisionId }: { rows: StandingsTableRow[]; divisionId: string }) {
  return <table className='w-full table-fixed text-sm'>
    <colgroup>
      <col className='w-12' />
      <col />
      <col className='w-10 sm:w-11' />
      <col className='w-10 sm:w-11' />
    </colgroup>
    <thead>
      <tr className='border-b bg-slate-100 text-left text-slate-600'>
        <th className='px-2 py-3 sm:px-3'>Rank</th>
        <th className='px-2 py-3 sm:px-3'>Team</th>
        <th className='px-1 py-3 text-center'>W</th>
        <th className='px-1 py-3 text-center'>L</th>
      </tr>
    </thead>
    <tbody>{rows.map(row => {
      const communityName = row.organization_name || row.community_name || 'Community';
      return <tr key={row.team_id || `${divisionId}-${row.team_name}`} className='border-b transition-colors last:border-0 hover:bg-slate-50'>
        <td className='px-2 py-3 font-bold sm:px-3'>{row.rank}</td>
        <td className='px-2 py-3 sm:px-3'>
          <div className='flex items-center gap-2.5'>
            <CommunityLogo src={row.community_logo_url} name={communityName} altText={row.community_logo_alt_text} size={28} className='h-7 w-7 shrink-0 p-0.5 sm:h-8 sm:w-8' />
            <span className='min-w-0 whitespace-normal break-words font-semibold text-slate-900'>{row.team_name}</span>
          </div>
        </td>
        <td className='px-1 py-3 text-center'>{row.wins}</td>
        <td className='px-1 py-3 text-center'>{row.losses}</td>
      </tr>;
    })}</tbody>
  </table>;
}
