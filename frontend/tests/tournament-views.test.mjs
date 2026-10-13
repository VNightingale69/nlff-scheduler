import assert from 'node:assert/strict';
import { tournamentViews } from '../src/lib/tournamentViews.ts';
const entries = [
  { id: 'single', name: '2026 Fall Flag Tournament Single Elimination', season_id: 'fall26' },
  { id: 'double', name: '2026 Fall Flag Tournament Double Elimination', season_id: 'fall26' },
  { id: 'other', name: '2026 Spring Tournament', season_id: 'spring26' },
  { id: 'next', name: '2027 Tournament', season_id: 'fall27' },
];
const before = JSON.stringify(entries);
const views = tournamentViews(entries);
assert.equal(views.length, 3);
assert.equal(views[0].name, '2026 Tournament View');
assert.deepEqual(views[0].tournaments.map(t => t.id), ['single', 'double']);
assert.equal(views[1].name, '2026 Spring Tournament');
assert.equal(JSON.stringify(entries), before);
assert.equal(tournamentViews([{id:'a',name:'A'}, {id:'b',name:'B'}]).length, 2);
assert.deepEqual(tournamentViews([]), []);
console.log('Combined tournament views: both formats grouped by season; unrelated seasons and original records preserved.');
