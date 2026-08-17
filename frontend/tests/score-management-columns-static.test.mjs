import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/(dashboard)/admin/scores/page.tsx', import.meta.url), 'utf8');

assert.match(
  source,
  /const scoreTableHeaders = \[[^\]]*'Home Team','Home Score','Away Team','Away Score'/,
  'Score Management should display each score immediately after its team',
);
assert.match(
  source,
  /\{g\.home_team_name\}<\/td><td className=\{scoreColumnClass\}><input[^>]*value=\{d\.home_score\}[^>]*onChange=\{\(e\) => setDraft\(g, \{ home_score: e\.target\.value \}\)\}/,
  'the Home Score input should remain bound to the home score draft',
);
assert.match(
  source,
  /\{g\.away_team_name\}<\/td><td className=\{scoreColumnClass\}><input[^>]*value=\{d\.away_score\}[^>]*onChange=\{\(e\) => setDraft\(g, \{ away_score: e\.target\.value \}\)\}/,
  'the Away Score input should remain bound to the away score draft',
);
assert.match(source, /const save = \(g: ScoreGame\) => act\('Score correction saved\.'/);
assert.match(source, /const approve = \(g: ScoreGame\) => act\('Score approved\.'/);
assert.match(source, /const publish = \(g: ScoreGame\) => act\('Score published\.'/);
assert.match(source, /const unpublish = async \(g: ScoreGame\)/);
assert.match(source, /const history = async \(g: ScoreGame\)/);

console.log('Score Management column order checks passed.');
