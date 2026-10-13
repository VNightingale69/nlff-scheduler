"""Seeded double-elimination graph with one grand final (no reset)."""
import math
from app.models import TournamentGame


def generate(db, td, entrants, seed_order):
    size = 2 ** math.ceil(math.log2(len(entrants)))
    seeds = {i: ('team', tt.team_id, tt.seed) for i, tt in enumerate(entrants, 1)}
    slots = [seeds.get(i) for i in seed_order(size)]
    counter = 0

    def play(left, right, name, round_number):
        nonlocal counter
        if left is None:
            return right, None
        if right is None:
            return left, None
        counter += 1
        game = TournamentGame(tournament_division_id=td.id, game_number=counter,
                              round_name=name, round_number=round_number,
                              status='READY' if left[0] == right[0] == 'team' else 'WAITING_FOR_TEAMS')
        for side, ref in [(1, left), (2, right)]:
            if ref[0] == 'team':
                setattr(game, f'team_{side}_id', ref[1])
                setattr(game, f'team_{side}_seed', ref[2])
            else:
                setattr(game, f'team_{side}_source_game_id', ref[1])
                setattr(game, f'team_{side}_source_outcome', ref[0])
        db.add(game); db.flush()
        return ('WINNER', game.id), ('LOSER', game.id)

    drops = []
    levels = int(math.log2(size))
    for level in range(1, levels + 1):
        name = ('Winners Final' if level == levels else 'Winners Play-In' if level == 1 and len(entrants) < size
                else 'Winners Semifinal' if level == levels - 1 else 'Winners Quarterfinal' if level == levels - 2 else f'Winners Round {level}')
        winners, losers = [], []
        for i in range(0, len(slots), 2):
            winner, loser = play(slots[i], slots[i + 1], name, level)
            winners.append(winner); losers.append(loser)
        slots = winners
        drops.append(losers)
    winners_champion = slots[0]
    if levels == 1:
        losers_champion = drops[0][0]
    else:
        loser_round = 0
        remaining = drops[0]
        def consolidate(refs):
            nonlocal loser_round
            loser_round += 1
            return [play(refs[i], refs[i + 1], f'Losers Round {loser_round}', levels + loser_round)[0]
                    for i in range(0, len(refs), 2)]
        remaining = consolidate(remaining)
        for level in range(1, levels):
            loser_round += 1
            incoming = list(reversed(drops[level]))
            name = 'Losers Final' if level == levels - 1 else f'Losers Round {loser_round}'
            remaining = [play(a, b, name, levels + loser_round)[0] for a, b in zip(remaining, incoming)]
            if len(remaining) > 1:
                remaining = consolidate(remaining)
        losers_champion = remaining[0]
    play(winners_champion, losers_champion, 'Grand Final', levels * 3)
    # Bye-only lower rounds do not appear as gaps in the user-facing numbering.
    lower = db.query(TournamentGame).filter_by(tournament_division_id=td.id).all()
    round_ids = sorted({g.round_number for g in lower if g.round_name.startswith('Losers')})
    for g in lower:
        if g.round_name.startswith('Losers') and g.round_name != 'Losers Final':
            g.round_name = f'Losers Round {round_ids.index(g.round_number) + 1}'
    td.status = 'BRACKET_GENERATED'
