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

// Bracket canvas headers use one shared header model for live and exported renderers.
assert.match(source, /type BracketHeaderData = \{/);
assert.match(source, /function bracketHeaderData\(title: string, division: TournamentBracketDivision, outputLabel\?: string\): BracketHeaderData/);
assert.match(source, /function BracketHeader\(\{ header \}: \{ header: BracketHeaderData \}\)/);
assert.match(source, /data-testid='bracket-canvas-header'/);
assert.match(source, /<BracketHeader header=\{header\} \/>/);
assert.match(source, /const header = bracketHeaderData\(title, division, outputLabel\);/);
assert.match(source, /const header = bracketHeaderData\(title, division, publicView \? 'Published bracket export' : 'Administrator bracket export'\);/);
assert.match(source, /svgText\(layout\.margin, 34, header\.tournamentName/);
assert.match(source, /svgText\(layout\.margin, 60, header\.divisionLabel/);
assert.match(source, /aria-label=\{`\$\{header\.tournamentName\} \$\{header\.divisionLabel\} bracket`\}/);
assert.match(source, /aria-label="\$\{escapeXml\(`\$\{header\.tournamentName\} \$\{header\.divisionLabel\} bracket`\)\}"/);
assert.doesNotMatch(source, /svgText\(layout\.margin, 60, `\$\{division\.division_group\} \$\{division\.division_name\}`/);

// Division labels are dynamic, prefer display names, and never render a blank division line.
const bracketDivisionLabelBody = source.match(/function bracketDivisionLabel\([^)]*\) \{([\s\S]*?)\n\}/)?.[1];
assert.ok(bracketDivisionLabelBody, 'bracketDivisionLabel should be present');
const bracketDivisionLabel = new Function('division', bracketDivisionLabelBody);
assert.equal(bracketDivisionLabel({ division_group: 'COED', division_name: 'K-1' }), 'COED K-1');
assert.equal(bracketDivisionLabel({ division_group: 'COED', division_name: '4-5' }), 'COED 4-5');
assert.equal(bracketDivisionLabel({ division_group: 'GIRLS', division_name: '3-5' }), 'GIRLS 3-5');
assert.equal(bracketDivisionLabel({ display_name: 'Girls 6-8 Showcase', division_group: 'GIRLS', division_name: '6-8' }), 'Girls 6-8 Showcase');
assert.equal(bracketDivisionLabel({ division_group: '', division_name: '' }), 'Division TBD');
assert.equal(bracketDivisionLabel({}), 'Division TBD');
