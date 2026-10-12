import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/components/TournamentBracket.tsx', import.meta.url), 'utf8');
// Execute the actual export/layout implementation, without mounting the UI.
const code = ts.transpileModule(source + '\nexport { buildBracketSvg, buildBracketLayout, teamNameLines, teamRowHeight, bracketConnectors, pdfFromJpegDataUrl, svgToCanvas };', { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText;
const module = { exports: {} };
new Function('require', 'exports', code)((name) => {
  if (name.includes('CommunityLogo')) return { logoSource: (url) => url };
  if (name.includes('displayFormat')) return { formatDisplayDate: (v) => v, formatDisplayTime: (v) => v };
  if (name.includes('publicFieldName')) return { publicFieldName: (v) => v };
  throw new Error(name);
}, module.exports);
const api = module.exports;
const names = ['Westosha Girls 6-8 Maroon', 'Prairie Ridge Girls 6-8 White', 'Prairie Ridge Girls 6-8 Maroon', 'Johnsburg Girls 6-8 Gold', 'Johnsburg Girls 6-8 Blue', 'WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW'];
let example;
for (const group of ['Girls', 'Coed']) for (const size of [2, 4, 8, 16, 32]) {
  const rounds = [];
  let previous = [];
  for (let count = size / 2, round = 1; count >= 1; count /= 2, round++) {
    const games = Array.from({ length: count }, (_, i) => ({ id: `${round}-${i}`, round_number: round, round_name: count === 1 ? 'Championship' : round === 1 ? 'Play-in' : 'Semifinal', game_number: i + 1, team_1_name: names[(i * 2) % names.length], team_2_name: names[(i * 2 + 1) % names.length], team_1_id: 'a', team_2_id: 'b', winner_team_id: 'a', winner_team_name: names[(i * 2) % names.length], team_1_seed: 1, team_2_seed: 2, home_score: 21, away_score: 7, status: 'COMPLETED', score_status: 'PUBLISHED', team_1_source_game_id: previous[i * 2]?.id, team_2_source_game_id: previous[i * 2 + 1]?.id, host_location_name: 'Community Sports Complex', field_name: 'Field 1', date: '2026-10-11', time: '12:00' }));
    rounds.push({ round_number: round, round_name: games[0].round_name, games });
    previous = games;
  }
  const division = { id: 'fixture', display_name: `${group} 6-8`, rounds };
  const before = JSON.stringify(division);
  const layout = api.buildBracketLayout(rounds);
  const svg = api.buildBracketSvg('Regression tournament', division, false);
  for (const round of rounds) {
    let bottom = 0;
    for (const game of round.games) {
      const pos = layout.positions.get(game.id);
      assert.ok(pos.y >= bottom);
      bottom = pos.y + pos.height;
      assert.ok(bottom < layout.height);
      for (const slot of [1, 2]) {
        const lines = api.teamNameLines(game, slot);
        assert.equal(lines.join('').replace(/\s/g, ''), game[`team_${slot}_name`].replace(/\s/g, ''));
        for (const line of lines) assert.ok(svg.includes(`>${line}</text>`));
        assert.ok(api.teamRowHeight(game, slot) >= 26 + lines.length * 16);
      }
    }
  }
  assert.equal(api.bracketConnectors(rounds, layout).length, size - 2);
  assert.equal(JSON.stringify(division), before, 'Export must not mutate tournament state');
  // The actual PDF writer must preserve at least 9pt names, even for 32 teams.
  const pdf = await api.pdfFromJpegDataUrl('data:image/jpeg;base64,/9j/2Q==', layout.width * 2, layout.height * 2).text();
  const [pw, ph] = pdf.match(/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]/).slice(1).map(Number);
  assert.ok(pw > ph);
  assert.ok(Math.min((pw - 48) / (layout.width * 2), (ph - 48) / (layout.height * 2)) >= 0.375 - 1e-9);
  if (group === 'Girls' && size === 8) example = { svg, division };
}
const consolation = { ...example.division.rounds.at(-1).games[0], id: 'consolation', round_name: 'Consolation', team_1_source_game_id: null, team_2_source_game_id: null };
const withConsolation = { ...example.division, rounds: example.division.rounds.map((round, i, all) => i === all.length - 1 ? { ...round, games: [...round.games, consolation] } : round) };
for (const publicView of [false, true]) {
  const svg = api.buildBracketSvg('Tournament', withConsolation, publicView);
  assert.ok(svg.includes('Consolation'));
  assert.ok(svg.includes('>Maroon</text>') && svg.includes('>White</text>'));
}
if (process.env.BRACKET_FIXTURE_PATH) writeFileSync(process.env.BRACKET_FIXTURE_PATH, JSON.stringify({ ...example, code }));
console.log('Bracket export regression passed: Girls/Coed, 2–32 teams, full suffixes, long tokens, rounds, geometry, PDF sizing, immutable data.');
