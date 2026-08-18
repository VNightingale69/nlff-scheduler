import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const results = readFileSync(new URL('../src/components/public/PublicResults.tsx', import.meta.url), 'utf8');
const bracket = readFileSync(new URL('../src/components/TournamentBracket.tsx', import.meta.url), 'utf8');
const helper = readFileSync(new URL('../src/lib/publicFieldName.ts', import.meta.url), 'utf8');

test('every public result renderer uses the shared field-name defense', () => {
  assert.match(results, /publicFieldName\(game\.field\)/);
  assert.match(bracket, /publicFieldName\(game\.field_name\)/);
});

test('the public helper recognizes retired and generated lifecycle markers', () => {
  assert.match(helper, /__retired_generated__/);
  assert.match(helper, /__generated__/);
  assert.match(helper, /retired_/);
});
