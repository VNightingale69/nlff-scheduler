import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/TournamentBracket.tsx', import.meta.url), 'utf8');

// Screen cards use dynamic layout positions and can grow rather than clipping fixed-height content.
assert.match(source, /style=\{\{ left: position\.x, top: position\.y, width: layout\.roundWidth, minHeight: position\.height,/);
assert.doesNotMatch(source, /style=\{\{ left: position\.x, top: position\.y, width: layout\.roundWidth, height: layout\.gameHeight,/);
assert.match(source, /className=\{`absolute z-10 overflow-visible rounded-xl border-2 p-3 pb-4 shadow-sm/);
assert.match(source, /className='relative shrink-0 overflow-visible rounded-2xl/);

// Metadata is rendered inside a compact key/value grid without truncation, so dashes and long values fit.
assert.match(source, /data-testid='bracket-game-metadata'/);
assert.match(source, /grid-cols-\[54px_minmax\(0,1fr\)\]/);
assert.match(source, /<dd className='min-w-0 whitespace-normal break-words'>\{detail\.value\}<\/dd>/);
assert.doesNotMatch(source, /<dd className='truncate'>\{game\.host_location_name \|\| '—'\}<\/dd>/);
assert.match(source, /\{ label: 'Date', value: formatDisplayDate\(game\.date \|\| ''\) \|\| '—' \}/);
assert.match(source, /\{ label: 'Time', value: formatDisplayTime\(game\.time \|\| ''\) \|\| '—' \}/);
assert.match(source, /\{ label: 'Host', value: game\.host_location_name \|\| '—' \}/);
assert.match(source, /\{ label: 'Field', value: game\.field_name \|\| '—' \}/);
assert.match(source, /\{ label: 'Winner', value: game\.winner_team_name \|\| '—' \}/);

// Card height expands based on wrapped metadata, including long host/field/winner values.
assert.match(source, /function gameCardHeight\(game: TournamentBracketGame\)/);
assert.match(source, /gameMetadata\(game\)\.reduce\(\(height, row\) => height \+ Math\.max\(1, metadataLines\(row\.value\)\.length\) \* 12, 0\)/);
assert.match(source, /return Math\.max\(BRACKET_CANVAS\.gameHeight, 154 \+ metadataHeight\);/);
assert.match(source, /return splitText\(value, 32\);/);
assert.match(source, /pushChunkedWord\(word\)/);

// Bracket positioning and connector lines use per-card dynamic heights, including championship cards.
assert.match(source, /positions = new Map<string, \{ x: number; y: number; height: number \}>\(\)/);
assert.match(source, /positions\.set\(game\.id, \{ x, y, height \}\)/);
assert.match(source, /const y1 = start\.y \+ start\.height \/ 2;/);
assert.match(source, /const y2 = end\.y \+ end\.height \/ 2;/);

// SVG/PNG/PDF exports share the same dynamic card dimensions and wrapped metadata rendering.
assert.match(source, /height="\$\{position\.height\}" rx="\$\{layout\.gameRadius\}"/);
assert.match(source, /gameMetadata\(game\)\.forEach\(\(detail\) => \{/);
assert.match(source, /metadataLines\(detail\.value\)\.forEach\(\(line, lineIndex\) => \{/);
assert.match(source, /detailY \+= Math\.max\(1, metadataLines\(detail\.value\)\.length\) \* 12;/);
