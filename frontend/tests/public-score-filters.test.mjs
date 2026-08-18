import assert from 'node:assert/strict';
import { filterPublicScores, formatGameDateOption } from '../src/lib/publicScoreFilters.ts';

const games = [
  { game_id: 'home-match', date: '2026-08-16', division_id: 'coed-45', home_organization_id: 'westosha', away_organization_id: 'johnsburg', is_official: true },
  { game_id: 'away-match', date: '2026-08-23', division_id: 'coed-45', home_organization_id: 'antioch', away_organization_id: 'westosha', is_official: true },
  { game_id: 'other', date: '2026-08-16', division_id: 'girls-35', home_organization_id: 'antioch', away_organization_id: 'johnsburg', is_official: true },
  { game_id: 'private', date: '2026-08-16', division_id: 'coed-45', home_organization_id: 'westosha', away_organization_id: 'antioch', is_official: false },
];

assert.deepEqual(filterPublicScores(games, { community: 'westosha', date: '', division: '' }).map(game => game.game_id), ['home-match', 'away-match']);
assert.deepEqual(filterPublicScores(games, { community: '', date: '2026-08-16', division: '' }).map(game => game.game_id), ['home-match', 'other']);
assert.deepEqual(filterPublicScores(games, { community: 'westosha', date: '2026-08-16', division: 'coed-45' }).map(game => game.game_id), ['home-match']);
assert.equal(formatGameDateOption('2026-08-16'), 'Sunday, Aug 16, 2026');

console.log('public score filter behavior tests passed');
