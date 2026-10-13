"""Match CSV schedules to existing tournament bracket structure without changing it."""
import csv
import hashlib
import io
import json
import re
from datetime import datetime

from app.models import Field, HostLocation


def key(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


def parse_csv(content):
    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')), strict=True)
    headers = [key(h) for h in reader.fieldnames or []]
    required = {'date', 'time', 'division', 'gameid', 'round', 'hostlocation', 'field', 'hometeam', 'awayteam'}
    missing = required - set(headers)
    if missing:
        raise ValueError('Missing tournament columns: ' + ', '.join(sorted(missing)))
    if len(headers) != len(set(headers)):
        raise ValueError('Duplicate CSV columns.')
    rows = [{key(k): str(v or '').strip() for k, v in row.items() if k is not None}
            for row in reader if any(row.values())]
    if not rows or len(rows) > 1000:
        raise ValueError('Provide between 1 and 1000 tournament games.')
    return rows


def preview(db, tournament, rows, skip_resets=False):
    divisions = {key(f'{td.division.division_group} {td.division.name}'): td for td in tournament.divisions}
    sites = db.query(HostLocation).filter(HostLocation.is_active.is_(True)).all()
    fields = db.query(Field).filter(Field.is_active.is_(True), Field.deleted_at.is_(None)).all()
    result, assignments, matched, pending = [], [], {}, list(enumerate(rows, 2))
    counts = {}
    for row in rows:
        ref = (key(row['division']), key(row['gameid']))
        counts[ref] = counts.get(ref, 0) + 1

    def participant(row, side):
        label = row[f'{side}team']
        source = re.fullmatch(r'(Winner|Loser) of\s+(?:Game\s+)?(.+)', label, re.I)
        if source:
            game = matched.get((key(row['division']), key(source[2])))
            return (source[1].upper(), game.id) if game else None
        return ('team', key(label))

    def game_participant(game, side):
        source = getattr(game, f'team_{side}_source_game_id')
        team = getattr(game, f'team_{side}')
        return (getattr(game, f'team_{side}_source_outcome'), source) if source else ('team', key(team.name if team else ''))

    # Resolve feeder games before later rounds; file order need not be bracket order.
    while pending:
        next_pending = []
        for number, row in pending:
            errors = []
            if skip_resets and (key(row['round']) == 'championshipreset' or key(row.get('status')) == 'conditional'):
                result.append({'row': number, 'division': row['division'], 'csv_game_id': row['gameid'], 'skipped': True, 'errors': []})
                continue
            ref = (key(row['division']), key(row['gameid']))
            td = divisions.get(ref[0])
            if counts[ref] != 1 or not ref[1]:
                errors.append('Game ID must be nonempty and unique within its division.')
            if not td:
                errors.append('Division is not present in this tournament.')
            unsupported = key(row['round']) == 'championshipreset' or key(row.get('status')) == 'conditional'
            double_game = ('loser' in row['round'].casefold() or row['round'].casefold().startswith('winners')
                           or key(row['round']) == 'grandfinal' or any(re.match(r'Loser of\b', row[f'{side}team'], re.I) for side in ('home', 'away')))
            if unsupported:
                errors.append('This tournament uses one final without a reset. Remove conditional reset rows.')
            if td and double_game and td.bracket_type != 'DOUBLE_ELIMINATION':
                errors.append('This division needs a double-elimination bracket. Select that format and regenerate before importing.')
            home, away = participant(row, 'home'), participant(row, 'away')
            if not errors and (home is None or away is None):
                next_pending.append((number, row))
                continue
            candidates = []
            if not errors:
                round_key = key(row['round'])
                if td.bracket_type != 'DOUBLE_ELIMINATION':
                    round_key = round_key.removeprefix('winners')
                if round_key == 'final':
                    round_key = 'championship'
                # Six/seven-team brackets call their first round Play-In;
                # CSVs may label those same matches Quarterfinal. Feeder matching
                # still verifies their exact place in the bracket.
                quarterfinal_alias = (td.bracket_type == 'SINGLE_ELIMINATION' and round_key == 'quarterfinal'
                                      and sum(tt.included for tt in td.teams) in {6, 7})
                candidates = [g for g in td.games if (key(g.round_name) == round_key or
                              (quarterfinal_alias and key(g.round_name) == 'playin')) and
                              {game_participant(g, 1), game_participant(g, 2)} == {home, away}]
                if len(candidates) != 1:
                    errors.append('No unique bracket match for this round and its teams/feeder games. Check seeds and bracket structure.')
            game = candidates[0] if len(candidates) == 1 else None
            if game:
                if game.id in {g.id for g in matched.values()}:
                    errors.append('Another CSV row already matches this bracket game.')
                # Verify explicit seed numbers, allowing home/away order differences.
                for side, p in [('home', home), ('away', away)]:
                    seed = row.get(f'{side}seed', '')
                    if p[0] == 'team' and seed and key(seed) != 'tbd':
                        index = 1 if game_participant(game, 1) == p else 2
                        if seed != str(getattr(game, f'team_{index}_seed')):
                            errors.append(f'{side.title()} seed differs from the saved bracket.')
                if not errors:
                    matched[ref] = game
            try:
                game_date = next(datetime.strptime(row['date'], fmt).date() for fmt in
                                 ['%m/%d/%Y', '%Y-%m-%d'] if _valid(row['date'], fmt))
                kickoff = next(datetime.strptime(row['time'], fmt).time() for fmt in
                               ['%I:%M %p', '%H:%M', '%H:%M:%S'] if _valid(row['time'], fmt))
            except StopIteration:
                errors.append('Invalid date or time. Use MM/DD/YYYY and h:mm AM/PM, or ISO values.')
                game_date = kickoff = None
            site_matches = [s for s in sites if key(s.name) == key(row['hostlocation'])]
            site = site_matches[0] if len(site_matches) == 1 else None
            field_matches = [f for f in fields if site and f.host_location_id == site.id and key(f.name) == key(row['field'])]
            field = field_matches[0] if len(field_matches) == 1 else None
            if not site:
                errors.append('Host location does not uniquely match an active location.')
            if not field:
                errors.append('Field does not uniquely match an active field at that location.')
            item = {'row': number, 'division': row['division'], 'csv_game_id': row['gameid'],
                    'game_number': game.game_number if game else None, 'matched_round': game.round_name if game else None, 'date': row['date'], 'time': row['time'],
                    'site': row['hostlocation'], 'field': row['field'], 'errors': errors}
            result.append(item)
            if not errors:
                assignments.append((game, game_date, kickoff, site, field, item))
        if len(next_pending) == len(pending):
            for number, row in next_pending:
                result.append({'row': number, 'division': row['division'], 'csv_game_id': row['gameid'],
                               'errors': ['Feeder game could not be matched; check earlier games and references.']})
            break
        pending = next_pending
    # Check the final proposed schedule, including games outside this upload.
    proposed = {g.id: (d, t, f.id) for g, d, t, s, f, item in assignments}
    slots = {}
    for td in tournament.divisions:
        for g in td.games:
            slot = proposed.get(g.id, (g.game_date, g.kickoff_time, g.field_id))
            if all(slot):
                slots.setdefault(slot, []).append(g.id)
    for g, d, t, s, f, item in assignments:
        if len(slots[(d, t, f.id)]) > 1:
            item['errors'].append('Multiple tournament games occupy this field at the same kickoff.')
    state = [(str(g.id), g.round_name, g.game_number, str(g.team_1_id), str(g.team_2_id),
              str(g.team_1_source_game_id), str(g.team_2_source_game_id), g.team_1_source_outcome, g.team_2_source_outcome, g.team_1_seed, g.team_2_seed,
              str(g.game_date), str(g.kickoff_time), str(g.host_location_id), str(g.field_id))
             for td in tournament.divisions for g in td.games]
    resolved = [(str(g.id), str(d), str(t), str(site.id), str(field.id)) for g, d, t, site, field, _item in assignments]
    schedule = {g.id: (d, t) for g, d, t, _s, _f, _item in assignments}
    for g, d, t, _s, _f, item in assignments:
        for source in (g.team_1_source_game_id, g.team_2_source_game_id):
            source_game = next((candidate for td in tournament.divisions for candidate in td.games if candidate.id == source), None) if source else None
            before = schedule.get(source, (source_game.game_date, source_game.kickoff_time) if source_game else (None, None))
            if all(before) and before >= (d, t):
                item['errors'].append('A feeder game must start before this game.')
    fingerprint = hashlib.sha256(json.dumps([rows, sorted(state), result, sorted(resolved)], sort_keys=True).encode()).hexdigest()
    errors = sum(bool(r['errors']) for r in result)
    return {'rows': sorted(result, key=lambda r: r['row']), 'rows_uploaded': len(rows),
            'valid_games': sum(not r['errors'] and not r.get('skipped') for r in result), 'skipped_rows': sum(bool(r.get('skipped')) for r in result), 'invalid_rows': errors, 'fingerprint': fingerprint,
            'is_published': tournament.is_published}, assignments


def _valid(value, fmt):
    try:
        datetime.strptime(value, fmt)
        return True
    except ValueError:
        return False
