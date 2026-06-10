'use client';

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

function teamName(game: TournamentBracketGame, slot: 1 | 2) {
  return slot === 1 ? game.team_1_name || game.team_1_placeholder : game.team_2_name || game.team_2_placeholder;
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
    <div className={`rounded border p-2 ${isWinner ? 'border-emerald-400 bg-emerald-50 font-semibold' : 'border-slate-200 bg-white'}`}>
      <div className='flex items-start justify-between gap-2'>
        <div>
          <div className='text-[11px] uppercase tracking-wide text-slate-500'>{formatSeed(seed)}</div>
          <div>{name || 'TBD'}</div>
          {autoAdvanced && <div className='mt-1 inline-flex rounded bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-800'>BYE · Auto-Advance</div>}
          {isWinner && <div className='mt-1 inline-flex rounded bg-emerald-600 px-2 py-0.5 text-[11px] font-semibold text-white'>Winner</div>}
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

function divisionsForExport(divisions: TournamentBracketDivision[]): ExportDivision[] {
  return divisions.map((division) => ({ ...division, rounds: roundsForDivision(division) }));
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
  const roundWidth = 300;
  const roundGap = 64;
  const gameHeight = 190;
  const gameGap = 34;
  const margin = 32;
  const headerHeight = 92;
  const rounds = division.rounds;
  const maxGames = Math.max(1, ...rounds.map((round) => round.games.length));
  const width = margin * 2 + rounds.length * roundWidth + Math.max(0, rounds.length - 1) * roundGap;
  const height = headerHeight + maxGames * (gameHeight + gameGap) + margin;
  const gamePositions = new Map<string, { x: number; y: number }>();
  let body = `<svg xmlns="${SVG_NS}" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeXml(`${title} ${division.division_group} ${division.division_name} bracket`)}">`;
  body += '<rect width="100%" height="100%" fill="#f8fafc"/>';
  body += svgText(margin, 34, title, { size: 22, weight: '700' });
  body += svgText(margin, 60, `${division.division_group} ${division.division_name}`, { size: 16, weight: '700', fill: '#334155' });
  body += svgText(width - margin, 60, publicView ? 'Published bracket export' : 'Administrator bracket export', { size: 11, fill: '#64748b', anchor: 'end' });

  rounds.forEach((round, roundIndex) => {
    const x = margin + roundIndex * (roundWidth + roundGap);
    body += `<rect x="${x}" y="${headerHeight - 28}" width="${roundWidth}" height="28" rx="8" fill="#0f172a"/>`;
    body += svgText(x + 14, headerHeight - 9, round.round_name, { size: 13, weight: '700', fill: '#ffffff' });
    const offset = ((maxGames - round.games.length) * (gameHeight + gameGap)) / 2;
    round.games.forEach((game, gameIndex) => {
      const y = headerHeight + offset + gameIndex * (gameHeight + gameGap);
      gamePositions.set(game.id, { x, y });
      const status = displayStatus(game, publicView);
      const statusFill = game.needs_review && !publicView ? '#fef3c7' : game.is_published ? '#dcfce7' : '#ffffff';
      const statusStroke = game.needs_review && !publicView ? '#f59e0b' : game.is_published ? '#10b981' : '#cbd5e1';
      body += `<rect x="${x}" y="${y}" width="${roundWidth}" height="${gameHeight}" rx="12" fill="${statusFill}" stroke="${statusStroke}" stroke-width="2"/>`;
      body += svgText(x + 14, y + 24, `${game.round_name} · Game ${game.game_number}`, { size: 12, weight: '700', fill: '#334155' });
      body += svgText(x + roundWidth - 14, y + 24, status, { size: 10, weight: '700', fill: '#475569', anchor: 'end' });
      ([1, 2] as const).forEach((slot, slotIndex) => {
        const rowY = y + 42 + slotIndex * 44;
        const winner = isWinningSlot(game, slot);
        const name = teamName(game, slot) || 'TBD';
        const seed = slot === 1 ? game.team_1_seed : game.team_2_seed;
        const score = slot === 1 ? game.home_score : game.away_score;
        const autoAdvanced = slot === 1 ? game.team_1_auto_advanced : game.team_2_auto_advanced;
        body += `<rect x="${x + 12}" y="${rowY}" width="${roundWidth - 24}" height="38" rx="8" fill="${winner ? '#ecfdf5' : '#ffffff'}" stroke="${winner ? '#10b981' : '#e2e8f0'}"/>`;
        body += svgText(x + 22, rowY + 14, seed ? `Seed ${seed}` : autoAdvanced ? 'BYE' : 'Seed TBD', { size: 9, fill: '#64748b' });
        body += svgText(x + 22, rowY + 30, splitText(name, 28)[0] || 'TBD', { size: 12, weight: winner ? '700' : '500' });
        if (winner) body += svgText(x + roundWidth - 54, rowY + 14, 'Winner', { size: 9, weight: '700', fill: '#047857' });
        body += svgText(x + roundWidth - 22, rowY + 30, score == null ? '—' : String(score), { size: 13, weight: '700', anchor: 'end' });
      });
      const details = [
        `Date: ${formatDisplayDate(game.date || '') || '—'}`,
        `Time: ${formatDisplayTime(game.time || '') || '—'}`,
        `Host: ${game.host_location_name || '—'}`,
        `Field: ${game.field_name || '—'}`,
        `Winner: ${game.winner_team_name || '—'}`,
      ];
      details.forEach((detail, index) => body += svgText(x + 14, y + 142 + index * 12, detail, { size: 10, fill: '#475569' }));
    });
  });

  rounds.forEach((round, roundIndex) => {
    if (roundIndex === rounds.length - 1) return;
    round.games.forEach((game) => {
      const start = gamePositions.get(game.id);
      if (!start) return;
      const nextRound = rounds[roundIndex + 1];
      const nextGame = nextRound.games.find((candidate) => candidate.team_1_source_game_id === game.id || candidate.team_2_source_game_id === game.id);
      const end = nextGame ? gamePositions.get(nextGame.id) : null;
      if (!end) return;
      const y1 = start.y + gameHeight / 2;
      const y2 = end.y + gameHeight / 2;
      const x1 = start.x + roundWidth;
      const midX = x1 + roundGap / 2;
      body += `<path d="M ${x1} ${y1} H ${midX} V ${y2} H ${end.x}" fill="none" stroke="#94a3b8" stroke-width="2"/>`;
    });
  });

  body += '</svg>';
  return body;
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
      {exportDivisions.map((division) => {
        const rounds = division.rounds;
        return (
          <section key={division.id} id={`division-${division.id}`} className='space-y-3'>
            <div className='flex flex-wrap items-start justify-between gap-3'>
              <div>
                <h3 className='text-lg font-semibold'>{division.division_group} {division.division_name}</h3>
                <p className='text-xs text-slate-500'>Bracket source: saved tournament game records and published tournament score advancement.</p>
              </div>
              {enableDownloads && <DownloadControls title={tournamentTitle} division={division} publicView={publicView} />}
            </div>
            <div className='overflow-x-auto pb-2'>
              <div className='grid min-w-max auto-cols-[19rem] grid-flow-col gap-6'>
                {rounds.map((round) => (
                  <div key={round.round_number} className='space-y-3'>
                    <div className='sticky left-0 rounded bg-slate-900 px-3 py-2 text-sm font-semibold text-white'>{round.round_name}</div>
                    <div className='space-y-4'>
                      {round.games.map((game) => (
                        <article key={game.id} className={`relative rounded-lg border p-3 shadow-sm ${statusClass(game, publicView)} after:absolute after:left-full after:top-1/2 after:hidden after:h-px after:w-6 after:bg-slate-300 md:after:block`}>
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
