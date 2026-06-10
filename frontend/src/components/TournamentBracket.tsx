'use client';

import CommunityLogo, { logoSource } from '@/components/CommunityLogo';
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
  team_1_logo_url?: string | null;
  team_2_logo_url?: string | null;
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
  team_1_source_game_id?: string | null;
  team_2_source_game_id?: string | null;
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
  tournamentTitle?: string;
  enableDownloads?: boolean;
};

type ExportDivision = TournamentBracketDivision & { rounds: TournamentBracketRound[] };

type BracketLayout = {
  width: number;
  height: number;
  roundWidth: number;
  roundGap: number;
  gameHeight: number;
  gameGap: number;
  margin: number;
  headerHeight: number;
  roundHeaderHeight: number;
  roundHeaderRadius: number;
  gameRadius: number;
  teamRowHeight: number;
  teamRowRadius: number;
  connectorStroke: string;
  connectorWidth: number;
  positions: Map<string, { x: number; y: number }>;
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

const SVG_NS = 'http://www.w3.org/2000/svg';
const BRACKET_CANVAS = {
  roundWidth: 300,
  roundGap: 64,
  gameHeight: 220,
  gameGap: 34,
  margin: 32,
  headerHeight: 92,
  roundHeaderHeight: 28,
  roundHeaderRadius: 8,
  gameRadius: 12,
  teamRowHeight: 38,
  teamRowRadius: 8,
  connectorStroke: '#94a3b8',
  connectorWidth: 2,
} as const;

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

function statusVisual(game: TournamentBracketGame, publicView?: boolean) {
  if (game.needs_review && !publicView) return { fill: '#fef3c7', stroke: '#f59e0b' };
  if (game.is_published) return { fill: '#dcfce7', stroke: '#10b981' };
  return { fill: '#ffffff', stroke: '#cbd5e1' };
}

function formatSeed(seed?: number | null) {
  return seed ? `Seed ${seed}` : 'Seed TBD';
}

function teamName(game: TournamentBracketGame, slot: 1 | 2) {
  return slot === 1 ? game.team_1_name || game.team_1_placeholder : game.team_2_name || game.team_2_placeholder;
}

function teamLogoUrl(game: TournamentBracketGame, slot: 1 | 2) {
  return slot === 1 ? game.team_1_logo_url : game.team_2_logo_url;
}

function isWinningSlot(game: TournamentBracketGame, slot: 1 | 2) {
  const teamId = slot === 1 ? game.team_1_id : game.team_2_id;
  return Boolean(game.winner_team_id && teamId && game.winner_team_id === teamId);
}

function TeamRow({ game, slot }: { game: TournamentBracketGame; slot: 1 | 2 }) {
  const name = teamName(game, slot);
  const seed = slot === 1 ? game.team_1_seed : game.team_2_seed;
  const score = slot === 1 ? game.home_score : game.away_score;
  const autoAdvanced = slot === 1 ? game.team_1_auto_advanced : game.team_2_auto_advanced;
  const isWinner = isWinningSlot(game, slot);

  return (
    <div className={`h-[38px] rounded-lg border px-2.5 py-1.5 ${isWinner ? 'border-emerald-500 bg-emerald-50 font-semibold' : 'border-slate-200 bg-white'}`}>
      <div className='flex items-start justify-between gap-2'>
        <div className='flex min-w-0 items-center gap-2'>
          <CommunityLogo src={teamLogoUrl(game, slot)} name={name} size={28} />
          <div className='min-w-0'>
            <div className='text-[9px] leading-3 text-slate-500'>{seed ? `Seed ${seed}` : autoAdvanced ? 'BYE' : 'Seed TBD'}</div>
            <div className='truncate text-xs leading-4 text-slate-900'>{name || 'TBD'}</div>
          </div>
        </div>
        <div className='flex min-w-[56px] flex-col items-end'>
          {isWinner && <div className='text-[9px] font-bold leading-3 text-emerald-700'>Winner</div>}
          <div className='text-right text-[13px] font-bold leading-4 text-slate-900'>{score ?? '—'}</div>
        </div>
      </div>
      {autoAdvanced && <span className='sr-only'>BYE · Auto-Advance</span>}
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

function divisionsForExport(divisions: TournamentBracketDivision[]): ExportDivision[] {
  return divisions.map((division) => ({ ...division, rounds: roundsForDivision(division) }));
}

function buildBracketLayout(rounds: TournamentBracketRound[]): BracketLayout {
  const maxGames = Math.max(1, ...rounds.map((round) => round.games.length));
  const width = BRACKET_CANVAS.margin * 2 + rounds.length * BRACKET_CANVAS.roundWidth + Math.max(0, rounds.length - 1) * BRACKET_CANVAS.roundGap;
  const height = BRACKET_CANVAS.headerHeight + maxGames * (BRACKET_CANVAS.gameHeight + BRACKET_CANVAS.gameGap) + BRACKET_CANVAS.margin;
  const positions = new Map<string, { x: number; y: number }>();

  rounds.forEach((round, roundIndex) => {
    const x = BRACKET_CANVAS.margin + roundIndex * (BRACKET_CANVAS.roundWidth + BRACKET_CANVAS.roundGap);
    const offset = ((maxGames - round.games.length) * (BRACKET_CANVAS.gameHeight + BRACKET_CANVAS.gameGap)) / 2;
    round.games.forEach((game, gameIndex) => {
      positions.set(game.id, { x, y: BRACKET_CANVAS.headerHeight + offset + gameIndex * (BRACKET_CANVAS.gameHeight + BRACKET_CANVAS.gameGap) });
    });
  });

  return { ...BRACKET_CANVAS, width, height, positions };
}

function connectorPath(start: { x: number; y: number }, end: { x: number; y: number }, layout: BracketLayout) {
  const y1 = start.y + layout.gameHeight / 2;
  const y2 = end.y + layout.gameHeight / 2;
  const x1 = start.x + layout.roundWidth;
  const midX = x1 + layout.roundGap / 2;
  return `M ${x1} ${y1} H ${midX} V ${y2} H ${end.x}`;
}

function bracketConnectors(rounds: TournamentBracketRound[], layout: BracketLayout) {
  return rounds.flatMap((round, roundIndex) => {
    if (roundIndex === rounds.length - 1) return [];
    return round.games.flatMap((game) => {
      const start = layout.positions.get(game.id);
      if (!start) return [];
      const nextRound = rounds[roundIndex + 1];
      const nextGame = nextRound.games.find((candidate) => candidate.team_1_source_game_id === game.id || candidate.team_2_source_game_id === game.id);
      if (!nextGame) return [];
      const end = layout.positions.get(nextGame.id);
      if (!end) return [];
      return [{ id: `${game.id}-${nextGame.id}`, d: connectorPath(start, end, layout) }];
    });
  });
}

function escapeXml(value: unknown) {
  return String(value ?? '').replace(/[<>&"']/g, (char) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[char] || char));
}

function sanitizeFilename(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'tournament-bracket';
}

function splitText(value: string, max = 30) {
  const words = value.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let current = '';
  words.forEach((word) => {
    const next = current ? `${current} ${word}` : word;
    if (next.length > max && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  });
  if (current) lines.push(current);
  return lines.slice(0, 2);
}

function svgText(x: number, y: number, text: string, options: { size?: number; weight?: string; fill?: string; anchor?: string } = {}) {
  return `<text x="${x}" y="${y}" font-family="Inter, Arial, sans-serif" font-size="${options.size || 12}" font-weight="${options.weight || 400}" fill="${options.fill || '#0f172a'}"${options.anchor ? ` text-anchor="${options.anchor}"` : ''}>${escapeXml(text)}</text>`;
}

function buildBracketSvg(title: string, division: ExportDivision, publicView: boolean) {
  const rounds = division.rounds;
  const layout = buildBracketLayout(rounds);
  let body = `<svg xmlns="${SVG_NS}" width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" role="img" aria-label="${escapeXml(`${title} ${division.division_group} ${division.division_name} bracket`)}">`;
  body += '<rect width="100%" height="100%" fill="#f8fafc"/>';
  body += svgText(layout.margin, 34, title, { size: 22, weight: '700' });
  body += svgText(layout.margin, 60, `${division.division_group} ${division.division_name}`, { size: 16, weight: '700', fill: '#334155' });
  body += svgText(layout.width - layout.margin, 60, publicView ? 'Published bracket export' : 'Administrator bracket export', { size: 11, fill: '#64748b', anchor: 'end' });

  bracketConnectors(rounds, layout).forEach((connector) => {
    body += `<path d="${connector.d}" fill="none" stroke="${layout.connectorStroke}" stroke-width="${layout.connectorWidth}"/>`;
  });

  rounds.forEach((round, roundIndex) => {
    const x = layout.margin + roundIndex * (layout.roundWidth + layout.roundGap);
    body += `<rect x="${x}" y="${layout.headerHeight - 28}" width="${layout.roundWidth}" height="${layout.roundHeaderHeight}" rx="${layout.roundHeaderRadius}" fill="#0f172a"/>`;
    body += svgText(x + 14, layout.headerHeight - 9, round.round_name, { size: 13, weight: '700', fill: '#ffffff' });
    round.games.forEach((game) => {
      const position = layout.positions.get(game.id);
      if (!position) return;
      const { x: gameX, y } = position;
      const status = displayStatus(game, publicView);
      const statusColors = statusVisual(game, publicView);
      body += `<rect x="${gameX}" y="${y}" width="${layout.roundWidth}" height="${layout.gameHeight}" rx="${layout.gameRadius}" fill="${statusColors.fill}" stroke="${statusColors.stroke}" stroke-width="2"/>`;
      body += svgText(gameX + 14, y + 24, `${game.round_name} · Game ${game.game_number}`, { size: 12, weight: '700', fill: '#334155' });
      body += svgText(gameX + layout.roundWidth - 14, y + 24, status, { size: 10, weight: '700', fill: '#475569', anchor: 'end' });
      ([1, 2] as const).forEach((slot, slotIndex) => {
        const rowY = y + 42 + slotIndex * 44;
        const winner = isWinningSlot(game, slot);
        const name = teamName(game, slot) || 'TBD';
        const seed = slot === 1 ? game.team_1_seed : game.team_2_seed;
        const score = slot === 1 ? game.home_score : game.away_score;
        const autoAdvanced = slot === 1 ? game.team_1_auto_advanced : game.team_2_auto_advanced;
        body += `<rect x="${gameX + 12}" y="${rowY}" width="${layout.roundWidth - 24}" height="${layout.teamRowHeight}" rx="${layout.teamRowRadius}" fill="${winner ? '#ecfdf5' : '#ffffff'}" stroke="${winner ? '#10b981' : '#e2e8f0'}"/>`;
        const logo = logoSource(teamLogoUrl(game, slot));
        if (logo) {
          body += `<image href="${escapeXml(logo)}" x="${gameX + 20}" y="${rowY + 6}" width="28" height="28" preserveAspectRatio="xMidYMid meet"/>`;
        } else {
          body += `<circle cx="${gameX + 34}" cy="${rowY + 20}" r="14" fill="#f1f5f9" stroke="#cbd5e1"/>`;
          body += svgText(gameX + 34, rowY + 24, (name || 'C').split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase(), { size: 9, weight: '700', fill: '#475569', anchor: 'middle' });
        }
        body += svgText(gameX + 56, rowY + 14, seed ? `Seed ${seed}` : autoAdvanced ? 'BYE' : 'Seed TBD', { size: 9, fill: '#64748b' });
        body += svgText(gameX + 56, rowY + 30, splitText(name, 24)[0] || 'TBD', { size: 12, weight: winner ? '700' : '500' });
        if (winner) body += svgText(gameX + layout.roundWidth - 54, rowY + 14, 'Winner', { size: 9, weight: '700', fill: '#047857' });
        body += svgText(gameX + layout.roundWidth - 22, rowY + 30, score == null ? '—' : String(score), { size: 13, weight: '700', anchor: 'end' });
      });
      const details = [
        `Date: ${formatDisplayDate(game.date || '') || '—'}`,
        `Time: ${formatDisplayTime(game.time || '') || '—'}`,
        `Host: ${game.host_location_name || '—'}`,
        `Field: ${game.field_name || '—'}`,
        `Winner: ${game.winner_team_name || '—'}`,
      ];
      details.forEach((detail, index) => { body += svgText(gameX + 14, y + 142 + index * 12, detail, { size: 10, fill: '#475569' }); });
    });
  });

  body += '</svg>';
  return body;
}

function SharedBracketRenderer({ title, division, publicView, outputLabel }: { title: string; division: ExportDivision; publicView: boolean; outputLabel: string }) {
  const rounds = division.rounds;
  const layout = buildBracketLayout(rounds);

  return (
    <div
      className='relative shrink-0 overflow-hidden rounded-2xl bg-slate-50 text-slate-900 shadow-inner ring-1 ring-slate-200'
      style={{ width: layout.width, height: layout.height, minWidth: layout.width }}
      role='img'
      aria-label={`${title} ${division.division_group} ${division.division_name} bracket`}
      data-shared-bracket-renderer='true'
    >
      <div className='absolute left-8 top-[26px]'>
        <h4 className='text-[22px] font-bold leading-7 text-slate-900'>{title}</h4>
        <p className='mt-0.5 text-base font-bold text-slate-700'>{division.division_group} {division.division_name}</p>
      </div>
      <div className='absolute right-8 top-[50px] text-[11px] text-slate-500'>{outputLabel}</div>

      <svg className='pointer-events-none absolute inset-0 z-0' width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} aria-hidden='true'>
        {bracketConnectors(rounds, layout).map((connector) => (
          <path key={connector.id} d={connector.d} fill='none' stroke={layout.connectorStroke} strokeWidth={layout.connectorWidth} />
        ))}
      </svg>

      {rounds.map((round, roundIndex) => {
        const x = layout.margin + roundIndex * (layout.roundWidth + layout.roundGap);
        return (
          <div key={round.round_number}>
            <div
              className='absolute z-10 rounded-lg bg-slate-900 px-3.5 py-1.5 text-[13px] font-bold text-white shadow-sm'
              style={{ left: x, top: layout.headerHeight - 28, width: layout.roundWidth, height: layout.roundHeaderHeight }}
            >
              {round.round_name}
            </div>
            {round.games.map((game) => {
              const position = layout.positions.get(game.id);
              if (!position) return null;
              const visual = statusVisual(game, publicView);
              return (
                <article
                  key={game.id}
                  className={`absolute z-10 rounded-xl border-2 p-3 shadow-sm ${statusClass(game, publicView)}`}
                  style={{ left: position.x, top: position.y, width: layout.roundWidth, minHeight: layout.gameHeight, backgroundColor: visual.fill, borderColor: visual.stroke }}
                >
                  <div className='mb-3 flex items-start justify-between gap-2'>
                    <div className='min-w-0'>
                      <div className='truncate text-xs font-bold text-slate-700'>{game.round_name} · Game {game.game_number}</div>
                    </div>
                    <span className='max-w-[110px] truncate rounded-full border border-slate-300 bg-white/80 px-2 py-0.5 text-[10px] font-bold text-slate-600'>{displayStatus(game, publicView)}</span>
                  </div>
                  <div className='space-y-1.5'>
                    <TeamRow game={game} slot={1} />
                    <TeamRow game={game} slot={2} />
                  </div>
                  <dl className='mt-3 grid grid-cols-[54px_1fr] gap-x-1 gap-y-0.5 text-[10px] leading-3 text-slate-600'>
                    <dt className='font-medium'>Date:</dt><dd className='truncate'>{formatDisplayDate(game.date || '') || '—'}</dd>
                    <dt className='font-medium'>Time:</dt><dd className='truncate'>{formatDisplayTime(game.time || '') || '—'}</dd>
                    <dt className='font-medium'>Host:</dt><dd className='truncate'>{game.host_location_name || '—'}</dd>
                    <dt className='font-medium'>Field:</dt><dd className='truncate'>{game.field_name || '—'}</dd>
                    <dt className='font-medium'>Winner:</dt><dd className='truncate'>{game.winner_team_name || '—'}</dd>
                  </dl>
                </article>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function loadImage(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.crossOrigin = 'anonymous';
    image.src = src;
  });
}

async function svgToCanvas(svg: string) {
  const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  const image = await loadImage(dataUrl);
  const canvas = document.createElement('canvas');
  canvas.width = image.width * 2;
  canvas.height = image.height * 2;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas rendering is not available.');
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.scale(2, 2);
  context.drawImage(image, 0, 0);
  return canvas;
}

function pdfFromJpegDataUrl(jpegDataUrl: string, width: number, height: number) {
  const binary = atob(jpegDataUrl.split(',')[1]);
  const pageWidth = 792;
  const pageHeight = 612;
  const scale = Math.min((pageWidth - 48) / width, (pageHeight - 48) / height);
  const imageWidth = width * scale;
  const imageHeight = height * scale;
  const x = (pageWidth - imageWidth) / 2;
  const y = (pageHeight - imageHeight) / 2;
  const contentStream = `q ${imageWidth.toFixed(2)} 0 0 ${imageHeight.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)} cm /Im0 Do Q`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>`,
    `<< /Length ${contentStream.length} >>\nstream\n${contentStream}\nendstream`,
    `<< /Type /XObject /Subtype /Image /Width ${width} /Height ${height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${binary.length} >>\nstream\n${binary}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  offsets.slice(1).forEach((offset) => { pdf += `${String(offset).padStart(10, '0')} 00000 n \n`; });
  pdf += `trailer << /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  const bytes = new Uint8Array(pdf.length);
  for (let index = 0; index < pdf.length; index += 1) bytes[index] = pdf.charCodeAt(index) & 0xff;
  return new Blob([bytes], { type: 'application/pdf' });
}

function DownloadControls({ title, division, publicView }: { title: string; division: ExportDivision; publicView: boolean }) {
  const filenameBase = sanitizeFilename(`${title}-${division.division_group}-${division.division_name}-bracket`);
  const svg = () => buildBracketSvg(title, division, publicView);
  const downloadSvg = () => downloadBlob(new Blob([svg()], { type: 'image/svg+xml;charset=utf-8' }), `${filenameBase}.svg`);
  const downloadPng = async () => {
    const canvas = await svgToCanvas(svg());
    canvas.toBlob((blob) => { if (blob) downloadBlob(blob, `${filenameBase}.png`); }, 'image/png');
  };
  const downloadPdf = async () => {
    const canvas = await svgToCanvas(svg());
    const pdf = pdfFromJpegDataUrl(canvas.toDataURL('image/jpeg', 0.92), canvas.width, canvas.height);
    downloadBlob(pdf, `${filenameBase}.pdf`);
  };

  return (
    <div className='flex flex-wrap items-center gap-2 text-sm print:hidden'>
      <span className='text-xs font-medium uppercase tracking-wide text-slate-500'>Download {division.division_group} {division.division_name}</span>
      <button className='rounded border px-3 py-1 hover:bg-slate-50' onClick={downloadPdf}>Download PDF</button>
      <button className='rounded border px-3 py-1 hover:bg-slate-50' onClick={downloadPng}>Download PNG</button>
      <button className='rounded border px-3 py-1 hover:bg-slate-50' onClick={downloadSvg}>Download SVG</button>
    </div>
  );
}

export default function TournamentBracket({ divisions, publicView = false, tournamentTitle = 'Tournament Bracket', enableDownloads = true }: Props) {
  const exportDivisions = divisionsForExport(divisions);
  if (!divisions.length) return <div className='rounded border p-4 text-sm text-slate-600'>No tournament bracket games are available.</div>;

  return (
    <div className='space-y-8'>
      <div className='flex flex-wrap gap-2 text-xs'>
        {['Ready', 'Waiting for Teams', 'Score Submitted', 'Official Final', publicView ? 'Pending Update' : 'Needs Review'].map((label) => (
          <span key={label} className='rounded-full border bg-white px-2 py-1 text-slate-700'>{label}</span>
        ))}
      </div>
      {exportDivisions.map((division) => (
        <section key={division.id} id={`division-${division.id}`} className='space-y-3'>
          <div className='flex flex-wrap items-start justify-between gap-3'>
            <div>
              <h3 className='text-lg font-semibold'>{division.division_group} {division.division_name}</h3>
              <p className='text-xs text-slate-500'>Bracket source: saved tournament game records and published tournament score advancement.</p>
            </div>
            {enableDownloads && <DownloadControls title={tournamentTitle} division={division} publicView={publicView} />}
          </div>
          <div className='overflow-x-auto overflow-y-auto pb-3' data-testid='bracket-horizontal-scroll'>
            <SharedBracketRenderer title={tournamentTitle} division={division} publicView={publicView} outputLabel={publicView ? 'Published bracket' : 'Administrator bracket'} />
          </div>
        </section>
      ))}
    </div>
  );
}
