"""Parsing and validation for staged CSV/XLSX schedule imports."""
import csv
import io
import re
from datetime import date, datetime, time, timedelta

from openpyxl import load_workbook

from app.models import (Division, Field, FieldInstance, Game, GameSlot, HostLocation,
                        HostLocationConfiguration, Season, Week)
from app.teams import resolve_roster_team, season_roster
from app.facility_layouts import (JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION,
                                  johnsburg_field_templates,
                                  johnsburg_location_name)
from app.services.field_resolution import resolve_active_field

REQUIRED = ('week', 'date', 'kickoff', 'site', 'field', 'fieldtype', 'division', 'hometeam', 'awayteam')


def _key(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').strip().lower())


def _text(value):
    return re.sub(r'\s+', ' ', str(value or '').strip())


def _normalized_name(value):
    return _text(value).casefold()


def _normalized_field_type(value):
    """Return a canonical individual field type, independent of layout labels."""
    normalized = _text(value).casefold()
    return normalized.upper() if normalized in {'small', 'medium', 'large'} else None


def _week_number(value):
    """Parse spreadsheet numbers and human-readable labels such as ``Week 1``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value > 0 else None
    match = re.fullmatch(r'(?:week\s*)?(\d+)', _text(value), re.IGNORECASE)
    number = int(match.group(1)) if match else None
    return number if number and number > 0 else None


def parse_schedule_file(filename: str, content: bytes):
    suffix = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if suffix == 'csv':
        rows = list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))
    elif suffix == 'xlsx':
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        rows = [list(row) for row in book.active.iter_rows(values_only=True)]
    else:
        raise ValueError('Only .csv and .xlsx schedule files are supported.')
    if not rows:
        raise ValueError('The import file is empty.')
    headers = [_key(value) for value in rows[0]]
    missing = [name for name in REQUIRED if name not in headers]
    if missing:
        raise ValueError('Missing required columns: ' + ', '.join(missing))
    return [{headers[i]: value for i, value in enumerate(row) if i < len(headers)}
            for row in rows[1:] if any(value not in (None, '') for value in row)]


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(_text(value), fmt).date()
        except ValueError:
            pass
    return None


def _time(value):
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, (float, int)) and 0 <= value < 1:
        return (datetime.min + timedelta(days=float(value))).time().replace(second=0, microsecond=0)
    for fmt in ('%I:%M %p', '%I:%M%p', '%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(_text(value).upper(), fmt).time()
        except ValueError:
            pass
    return None


def _configuration_candidates(db, site, field_name, field_type):
    """Return supported layouts containing this logical position and size.

    A supported facility layout is scheduling metadata in its own right.  It
    must remain usable by imports even when the corresponding layout is not the
    site's active/default ``HostLocationConfiguration`` (the import may be the
    reason the facility is reconfigured for that wave).
    """
    active = db.query(HostLocationConfiguration).filter_by(
        host_location_id=site.id, is_active=True,
    ).all()
    configured_by_code = {
        configuration.configuration_name.strip().upper().replace('-', '_').replace(' ', '_'): configuration
        for configuration in active
    }
    location = johnsburg_location_name(site)
    layout_codes = (JOHNSBURG_APPROVED_LAYOUT_CODES_BY_LOCATION.get(location, ())
                    if location else configured_by_code)
    candidates = {}
    requested_name = _normalized_name(field_name)
    if _normalized_name(getattr(site, 'name', '')) == 'hiller stadium' and requested_name == 'field 2':
        requested_name = 'field 3'
    for layout_code in layout_codes:
        configuration = configured_by_code.get(layout_code)
        templates = johnsburg_field_templates(site, layout_code)
        if configuration and configuration.members:
            templates = [(member.field.name, member.field.layout_type) for member in configuration.members
                         if member.field and member.field.is_active and member.field.deleted_at is None]
        if templates and any(
            _normalized_name(name) == requested_name
            and _key(template_type).startswith(_key(field_type))
            for name, template_type in templates
        ):
            candidates[layout_code] = configured_by_code.get(layout_code)
    return candidates


def build_preview(db, season_id, raw_rows):
    season = db.get(Season, season_id)
    weeks = {w.week_number: w for w in db.query(Week).filter(Week.season_id == season_id).all()}
    sites = {_key(x.name): x for x in db.query(HostLocation).filter(HostLocation.is_active.is_(True)).all()}
    all_divisions = db.query(Division).all()
    divisions = {_key(f'{x.division_group or ""} {x.name}'.strip()): x for x in all_divisions}
    divisions.update({_key(x.name): x for x in all_divisions})
    teams = season_roster(db, season_id)
    status_model = __import__('app.models', fromlist=['GameStatus']).GameStatus
    scheduled_status = db.query(status_model).filter_by(code='SCHEDULED').first()
    results, staged, game_keys, field_keys, team_keys = [], [], set(), set(), set()
    timeslot_rows = {}

    for number, raw in enumerate(raw_rows, 2):
        errors = []
        warnings = []
        source_week = _text(raw.get('week'))
        week_number = _week_number(raw.get('week'))
        week = weeks.get(week_number)
        game_date, kickoff = _date(raw.get('date')), _time(raw.get('kickoff'))
        if not week:
            errors.append(f'Week "{source_week}" could not be matched to a configured season week.')
        if not game_date:
            errors.append(f'Date "{_text(raw.get("date"))}" is invalid.')
        elif week and not (week.start_date <= game_date <= week.end_date):
            configured = week.primary_game_date or week.start_date
            errors.append(f'Week {week.week_number} is configured for {configured.strftime("%B %-d, %Y")}, but the imported date is {game_date.strftime("%B %-d, %Y")}.')
        if not kickoff:
            errors.append(f'Kickoff "{_text(raw.get("kickoff"))}" is invalid.')

        site = sites.get(_key(raw.get('site')))
        if not site:
            errors.append(f'Site "{_text(raw.get("site"))}" could not be found.')
        field = field_instance = None
        configuration_candidates = []
        if site:
            field = resolve_active_field(db, site, raw.get('field'))
            instances = db.query(FieldInstance).filter(FieldInstance.host_location_id == site.id, FieldInstance.is_active.is_(True)).all()
            field_instance = next((x for x in instances if _normalized_name(x.field_name) == _normalized_name(raw.get('field')) and (not game_date or x.instance_date == game_date)), None)
            # Generated/manual scheduling persists the dated field instance as
            # the playable assignment.  Its display name can include layout
            # terms, so prefer its canonical availability -> Field relationship
            # over trying to match that generated label to spreadsheet text.
            if field and not field_instance:
                field_instance = next((
                    x for x in instances
                    if (not game_date or x.instance_date == game_date)
                    and getattr(x.hosting_availability, 'field_id', None) == field.id
                ), None)
            # A dynamic position may exist only in a supported site layout.
            configuration_candidates = _configuration_candidates(
                db, site, raw.get('field'), raw.get('fieldtype'))
            if not field and not field_instance and not configuration_candidates:
                errors.append(f'Field "{_text(raw.get("field"))}" could not be found at site "{_text(raw.get("site"))}".')

        field_type = _normalized_field_type(raw.get('fieldtype'))
        configured_field_type = None
        if not field_type:
            errors.append('Field Type must be Small, Medium, or Large.')
        else:
            # ``Field.layout_type`` is the configured type of the canonical
            # field resolved above.  A dated instance can reflect a generated
            # layout, so it is only authoritative when no canonical Field was
            # resolved.  Site configuration names (for example FOUR_SMALL)
            # are deliberately not individual field types.
            resolved_type = (field.layout_type if field else None) or (
                field_instance.field_type if field_instance else None)
            canonical_field_type = _normalized_field_type(resolved_type)
            configured_field_type = canonical_field_type.title() if canonical_field_type else None
            type_mismatch = bool(canonical_field_type and canonical_field_type != field_type)
            # A field can be deliberately reconfigured for one timeslot.  Keep
            # this advisory separate from errors so it never prevents staging.
            if type_mismatch:
                if canonical_field_type:
                    warnings.append(
                        f'Field "{_text(raw.get("field"))}" is normally configured as '
                        f'"{canonical_field_type.title()}", but the import requests '
                        f'"{field_type.title()}". Verify the field will be '
                        'reconfigured for this timeslot.'
                    )

        division = divisions.get(_key(raw.get('division')))
        if not division:
            errors.append(f'Division "{_text(raw.get("division"))}" could not be found.')

        home_resolution = resolve_roster_team(teams, division, raw.get('hometeam'))
        away_resolution = resolve_roster_team(teams, division, raw.get('awayteam'))
        home, away = home_resolution.team, away_resolution.team
        season_name = season.name if season else 'selected'
        def resolution_error(side, value, resolution):
            imported = _text(value)
            if resolution.candidate_count > 1:
                return (f'Multiple active teams match "{imported}". '
                        'Import cannot continue until the team data is unambiguous.')
            parsed_community = resolution.community or 'Not recognized'
            parsed_team = resolution.team_name or 'Not recognized'
            return (f'Unable to resolve {side.lower()} team "{imported}". Parsed: '
                    f'Community: {parsed_community}; Division: {_text(raw.get("division"))}; '
                    f'Team: {parsed_team}; Season: {season_name}. '
                    'No matching active team was found.')
        if not home:
            errors.append(resolution_error('Home', raw.get('hometeam'), home_resolution))
        if not away:
            errors.append(resolution_error('Away', raw.get('awayteam'), away_resolution))
        if home and away and home.id == away.id:
            errors.append('Home Team and Away Team cannot be the same.')

        if week and game_date and kickoff and site and (field or field_instance or configuration_candidates) and home and away:
            identity = field.id if field else (field_instance.id if field_instance else _normalized_name(raw.get('field')))
            game_key = (week.id, game_date, kickoff, site.id, identity, home.id, away.id)
            field_key = (game_date, kickoff, site.id, identity)
            simultaneous = {(game_date, kickoff, home.id), (game_date, kickoff, away.id)}
            if game_key in game_keys:
                errors.append('Duplicate imported game.')
            if field_key in field_keys:
                errors.append('Field conflict at this date and kickoff.')
            if team_keys.intersection(simultaneous):
                errors.append('Team conflict at this date and kickoff.')
            game_keys.add(game_key); field_keys.add(field_key); team_keys.update(simultaneous)

        row = {'row': number, 'week': f'Week {week_number}' if week_number else source_week,
               'date': game_date.isoformat() if game_date else _text(raw.get('date')),
               'kickoff': kickoff.strftime('%H:%M') if kickoff else _text(raw.get('kickoff')),
               'site': _text(raw.get('site')), 'field': _text(raw.get('field')),
               'configured_field_type': configured_field_type,
               'imported_field_type': _text(raw.get('fieldtype')).title(),
               'division': _text(raw.get('division')), 'home_team': _text(raw.get('hometeam')),
               'away_team': _text(raw.get('awayteam')), 'notes': _text(raw.get('notes')) or None,
               'status': 'ERROR' if errors else ('WARNING' if warnings else 'VALID'),
               'message': ' '.join(errors + warnings) or 'Ready to import.'}
        results.append(row)
        if not errors:
            resolved_slot = None
            if field_instance and game_date and kickoff:
                resolved_slot = db.query(GameSlot).filter(
                    GameSlot.field_instance_id == field_instance.id,
                    GameSlot.slot_date == game_date,
                    GameSlot.start_time == kickoff,
                ).first()
            staged_row = {**row, 'week_number': week_number, 'week_id': str(week.id), 'site_id': str(site.id),
                           # Keep the source label for audit/preview, and keep the
                           # canonical relationship separately for confirmation.
                           # Confirmation must never need to resolve a name after
                           # the schedule being replaced has been deleted.
                           'imported_field_name': _text(raw.get('field')),
                           'resolved_field_id': str(field.id) if field else None,
                           'field_id': str(field.id) if field else None,
                           'field_layout_type_override': field_type if type_mismatch else None,
                           'field_instance_id': str(field_instance.id) if field_instance else None,
                           'game_slot_id': str(resolved_slot.id) if resolved_slot else None,
                           'home_team_id': str(home.id), 'away_team_id': str(away.id),
                           'game_status_id': str(scheduled_status.id) if scheduled_status else None}
            staged.append(staged_row)
            if configuration_candidates and game_date and kickoff:
                key = (site.id, game_date, kickoff)
                timeslot_rows.setdefault(key, []).append((
                    row, staged_row, configuration_candidates
                ))

    # A layout is a property of the complete site/date/kickoff wave, not of an
    # individual field record. Intersecting candidates rejects combinations
    # whose physical footprints overlap (for example Hiller Field 1 / Large and
    # Field 2 / Medium), even though each assignment is possible by itself.
    invalid_staged_ids = set()
    for (_site_id, _game_date, kickoff), grouped in timeslot_rows.items():
        common_ids = set(grouped[0][2])
        for _row, _staged_row, candidates in grouped[1:]:
            common_ids.intersection_update(candidates)
        if not common_ids:
            site_name = grouped[0][0]['site']
            message = (f'Imported assignments at {site_name} at {kickoff.strftime("%-I:%M %p")} '
                       'cannot be supported by any configured field layout.')
            for row, staged_row, _candidates in grouped:
                row['status'] = 'ERROR'; row['message'] = message
                invalid_staged_ids.add(id(staged_row))
        else:
            selected_code = sorted(common_ids)[0]
            selected = grouped[0][2][selected_code]
            layout = selected_code.replace('_', ' ').title()
            for row, staged_row, _candidates in grouped:
                staged_row['configuration_id'] = str(selected.id) if selected else None
                staged_row['configuration_name'] = selected_code
                layout_message = f'{row["site"]} will use its {layout} configuration for this timeslot.'
                row['message'] = (f'{row["message"]} {layout_message}' if row['status'] == 'WARNING'
                                  else f'Ready to import. {layout_message}')
    staged = [row for row in staged if id(row) not in invalid_staged_ids]

    affected = sorted({x['week_number'] for x in staged})
    existing = db.query(Game).join(Week, Game.week_id == Week.id).filter(
        Game.season_id == season_id, Week.week_number.in_(affected)).count() if affected else 0
    regular = {w.week_number for w in weeks.values() if w.date_type == 'REGULAR_SEASON'}
    dates = [_date(x['date']) for x in staged]
    warning_rows = [row for row in results if row['status'] == 'WARNING']
    diagnostics = [{
        'category': 'Scheduling Integrity',
        'check': 'Field configuration mismatch',
        'status': 'WARNING',
        'advisory': True,
        'blocking': False,
        'detail': {
            'site': row['site'], 'kickoff': row['kickoff'], 'field': row['field'],
            'configured_default_type': row['configured_field_type'],
            'imported_type': row['imported_field_type'],
            'message': row['message'],
        },
    } for row in warning_rows]
    return {'rows_uploaded': len(raw_rows), 'valid_games': len(staged),
            'importable_games': len(staged), 'invalid_rows': len(results) - len(staged),
            'weeks': affected, 'earliest_date': min(dates).isoformat() if dates else None,
            'latest_date': max(dates).isoformat() if dates else None, 'sites': sorted({x['site'] for x in staged}),
            'divisions': sorted({x['division'] for x in staged}), 'games_to_add': len(staged),
            'existing_games_to_replace': existing, 'warning_count': len(warning_rows),
            'blocking_errors': len(results) - len(staged),
            'is_full_regular_season': bool(regular) and set(affected) == regular,
            'diagnostics': diagnostics, 'rows': results}, staged
