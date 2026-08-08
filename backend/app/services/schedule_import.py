"""Parsing and validation for staged CSV/XLSX schedule imports."""
import csv
import io
import re
from datetime import date, datetime, time, timedelta

from openpyxl import load_workbook
from sqlalchemy import func
from app.models import Division, Field, Game, HostLocation, Team, Week

REQUIRED = ('week','date','kickoff','site','field','fieldtype','division','hometeam','awayteam')

def _key(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').strip().lower())

def _text(value):
    return str(value or '').strip()

def parse_schedule_file(filename: str, content: bytes):
    suffix = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
    if suffix == 'csv':
        text = content.decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(text)))
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
    return [{headers[i]: value for i, value in enumerate(row) if i < len(headers)} for row in rows[1:] if any(value not in (None, '') for value in row)]

def _date(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    for fmt in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y'):
        try: return datetime.strptime(_text(value), fmt).date()
        except ValueError: pass
    return None

def _time(value):
    if isinstance(value, datetime): return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time): return value.replace(second=0, microsecond=0)
    if isinstance(value, (float, int)) and 0 <= value < 1:
        return (datetime.min + timedelta(days=float(value))).time().replace(second=0, microsecond=0)
    for fmt in ('%I:%M %p','%I:%M%p','%H:%M','%H:%M:%S'):
        try: return datetime.strptime(_text(value).upper(), fmt).time()
        except ValueError: pass
    return None

def build_preview(db, season_id, raw_rows):
    weeks = {w.week_number: w for w in db.query(Week).filter(Week.season_id == season_id).all()}
    sites = {_key(x.name): x for x in db.query(HostLocation).filter(HostLocation.is_active.is_(True)).all()}
    divisions = {_key(f'{x.division_group or ""} {x.name}'.strip()): x for x in db.query(Division).all()}
    divisions.update({_key(x.name): x for x in db.query(Division).all()})
    teams = db.query(Team).filter(Team.is_active.is_(True), Team.deleted_at.is_(None)).all()
    status = db.query(__import__('app.models', fromlist=['GameStatus']).GameStatus).filter_by(code='SCHEDULED').first()
    results=[]; staged=[]; game_keys=set(); field_keys=set(); team_keys=set()
    for number, raw in enumerate(raw_rows, 2):
        errors=[]
        try: week_number=int(raw.get('week'))
        except (TypeError, ValueError): week_number=None
        week=weeks.get(week_number); game_date=_date(raw.get('date')); kickoff=_time(raw.get('kickoff'))
        if not week: errors.append('Invalid season week.')
        if not game_date: errors.append('Invalid date.')
        elif week and not (week.start_date <= game_date <= week.end_date): errors.append('Date is outside the specified week.')
        if not kickoff: errors.append('Invalid kickoff time.')
        site=sites.get(_key(raw.get('site')))
        if not site: errors.append('Site does not exist.')
        field=None
        if site:
            field=db.query(Field).filter(Field.host_location_id==site.id, Field.is_active.is_(True), Field.deleted_at.is_(None), func.lower(func.trim(Field.name))==_text(raw.get('field')).lower()).first()
            if not field: errors.append('Field does not exist at the specified site.')
        field_type=_text(raw.get('fieldtype')).upper()
        if field_type not in {'SMALL','MEDIUM','LARGE'}: errors.append('Field Type must be Small, Medium, or Large.')
        elif field and not _key(field.layout_type).startswith(_key(field_type)): errors.append('Field is incompatible with Field Type.')
        division=divisions.get(_key(raw.get('division')))
        if not division: errors.append('Division does not exist.')
        def team_named(value):
            matches=[t for t in teams if _key(t.name)==_key(value) and (not division or t.division_id==division.id)]
            return matches[0] if len(matches)==1 else None
        home=team_named(raw.get('hometeam')); away=team_named(raw.get('awayteam'))
        if not home: errors.append('Home Team is not an active team in the division.')
        if not away: errors.append('Away Team is not an active team in the division.')
        if home and away and home.id==away.id: errors.append('Home Team and Away Team cannot be the same.')
        if week and game_date and kickoff and site and field and home and away:
            game_key=(week.id,game_date,kickoff,site.id,field.id,home.id,away.id)
            field_key=(game_date,kickoff,site.id,field.id); simultaneous={(game_date,kickoff,home.id),(game_date,kickoff,away.id)}
            if game_key in game_keys: errors.append('Duplicate imported game.')
            if field_key in field_keys: errors.append('Field conflict at this date and kickoff.')
            if team_keys.intersection(simultaneous): errors.append('Team conflict at this date and kickoff.')
            game_keys.add(game_key); field_keys.add(field_key); team_keys.update(simultaneous)
        row={'row':number,'week':week_number,'date':game_date.isoformat() if game_date else _text(raw.get('date')),'kickoff':kickoff.strftime('%H:%M') if kickoff else _text(raw.get('kickoff')),'site':_text(raw.get('site')),'field':_text(raw.get('field')),'division':_text(raw.get('division')),'home_team':_text(raw.get('hometeam')),'away_team':_text(raw.get('awayteam')),'notes':_text(raw.get('notes')) or None,'status':'ERROR' if errors else 'VALID','message':' '.join(errors) or 'Ready to import.'}
        results.append(row)
        if not errors: staged.append({**row,'week_id':str(week.id),'site_id':str(site.id),'field_id':str(field.id),'home_team_id':str(home.id),'away_team_id':str(away.id),'game_status_id':str(status.id) if status else None})
    affected=sorted({x['week'] for x in staged}); existing=db.query(Game).join(Week, Game.week_id==Week.id).filter(Game.season_id==season_id, Week.week_number.in_(affected)).count() if affected else 0
    regular={w.week_number for w in weeks.values() if w.date_type=='REGULAR_SEASON'}
    dates=[_date(x['date']) for x in staged]
    return {'rows_uploaded':len(raw_rows),'valid_games':len(staged),'invalid_rows':len(results)-len(staged),'weeks':affected,'earliest_date':min(dates).isoformat() if dates else None,'latest_date':max(dates).isoformat() if dates else None,'sites':sorted({x['site'] for x in staged}),'divisions':sorted({x['division'] for x in staged}),'games_to_add':len(staged),'existing_games_to_replace':existing,'warning_count':0,'blocking_errors':len(results)-len(staged),'is_full_regular_season':bool(regular) and set(affected)==regular,'rows':results}, staged
