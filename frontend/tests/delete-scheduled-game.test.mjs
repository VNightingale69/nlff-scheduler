import assert from 'node:assert/strict';
import { deleteScheduledGame } from '../src/lib/deleteScheduledGame.mjs';

for (const scenario of ['success', 'failure', 'refresh failure']) {
  let games = [{ id: 'selected' }, { id: 'other' }];
  let edits = { selected: { notes: 'discard' }, other: { notes: 'keep' } };
  let dialogOpen = true;
  let error = '';
  let refreshed = false;
  await deleteScheduledGame({
    remove: async () => { if (scenario === 'failure') throw new Error('backend unavailable'); },
    commit: () => {
      games = games.filter((game) => game.id !== 'selected');
      delete edits.selected;
      dialogOpen = false;
    },
    refresh: async () => {
      refreshed = true;
      if (scenario === 'refresh failure') throw new Error('refresh unavailable');
    },
    failed: (e) => { error = e.message; },
    refreshFailed: (e) => { error = `deleted; ${e.message}`; },
  });
  assert.deepEqual(edits.other, { notes: 'keep' });
  assert.equal(games.length, scenario === 'failure' ? 2 : 1);
  assert.equal(dialogOpen, scenario === 'failure');
  assert.equal(refreshed, scenario !== 'failure');
  assert.equal(error, scenario === 'failure' ? 'backend unavailable' : scenario === 'refresh failure' ? 'deleted; refresh unavailable' : '');
}
console.log('scheduled game deletion behavior checks passed');
