import uuid
from dataclasses import dataclass, asdict
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session
from app.models import Team, Organization, Division, Game, GameStatus, GameSlot, GameScore, ScoreSubmission, ScoreHistory, ScheduleChangeLog, Tournament, TournamentDivision, TournamentTeam, TournamentGame

PUBLISHED_CODES = {'published', 'PUBLISHED'}

@dataclass
class OrphanedTeamReport:
    team_id: str
    team_name: str
    division: str | None
    season: str | None
    former_organization_id: str | None
    action: str
    reason: str | None = None


def find_orphaned_teams(db: Session):
    return (db.query(Team)
        .outerjoin(Organization, Team.organization_id == Organization.id)
        .filter(Team.organization_id.isnot(None), Organization.id.is_(None))
        .order_by(Team.name.asc()).all())


def _division_label(team: Team) -> str | None:
    if not team.division:
        return None
    return f'{team.division.division_group} {team.division.name}'


def _season_names(db: Session, team_id: uuid.UUID) -> str | None:
    rows = (db.query(Game.season_id).filter(or_(Game.home_team_id == team_id, Game.away_team_id == team_id)).distinct().all())
    ids = [r[0] for r in rows if r[0]]
    if not ids:
        return None
    from app.models import Season
    return ', '.join(name for (name,) in db.query(Season.name).filter(Season.id.in_(ids)).order_by(Season.name).all()) or None


def _published_reference_count(db: Session, team_id: uuid.UUID) -> int:
    published_game_count = (db.query(Game).join(GameStatus, Game.game_status_id == GameStatus.id)
        .filter(or_(Game.home_team_id == team_id, Game.away_team_id == team_id), GameStatus.code.in_(list(PUBLISHED_CODES))).count())
    published_score_count = (db.query(GameScore).join(Game, GameScore.game_id == Game.id)
        .filter(or_(Game.home_team_id == team_id, Game.away_team_id == team_id), GameScore.is_published.is_(True)).count())
    published_tournament_count = (db.query(TournamentGame).join(TournamentDivision, TournamentGame.tournament_division_id == TournamentDivision.id)
        .join(Tournament, TournamentDivision.tournament_id == Tournament.id)
        .filter(Tournament.is_published.is_(True), or_(TournamentGame.team_1_id == team_id, TournamentGame.team_2_id == team_id, TournamentGame.winner_team_id == team_id, TournamentGame.loser_team_id == team_id)).count())
    return published_game_count + published_score_count + published_tournament_count


def _delete_unpublished_team_dependencies(db: Session, team_id: uuid.UUID) -> dict[str, int]:
    unpublished_games = (db.query(Game.id).join(GameStatus, Game.game_status_id == GameStatus.id)
        .filter(or_(Game.home_team_id == team_id, Game.away_team_id == team_id), ~GameStatus.code.in_(list(PUBLISHED_CODES))).all())
    game_ids = [gid for (gid,) in unpublished_games]
    deleted = {}
    if game_ids:
        deleted['game_slots_unassigned'] = db.query(GameSlot).filter(GameSlot.assigned_game_id.in_(game_ids)).update({'assigned_game_id': None}, synchronize_session=False)
        deleted['score_history'] = db.query(ScoreHistory).filter(ScoreHistory.game_id.in_(game_ids)).delete(synchronize_session=False)
        deleted['score_submissions'] = db.query(ScoreSubmission).filter(ScoreSubmission.game_id.in_(game_ids)).delete(synchronize_session=False)
        deleted['game_scores'] = db.query(GameScore).filter(GameScore.game_id.in_(game_ids), GameScore.is_published.is_(False)).delete(synchronize_session=False)
        deleted['schedule_change_logs'] = db.query(ScheduleChangeLog).filter(ScheduleChangeLog.game_id.in_(game_ids)).delete(synchronize_session=False)
        deleted['games'] = db.query(Game).filter(Game.id.in_(game_ids)).delete(synchronize_session=False)
    deleted['tournament_games_cleared'] = db.query(TournamentGame).filter(or_(TournamentGame.team_1_id == team_id, TournamentGame.team_2_id == team_id, TournamentGame.winner_team_id == team_id, TournamentGame.loser_team_id == team_id)).update({'team_1_id': None, 'team_2_id': None, 'winner_team_id': None, 'loser_team_id': None}, synchronize_session=False)
    deleted['tournament_teams'] = db.query(TournamentTeam).filter(TournamentTeam.team_id == team_id).delete(synchronize_session=False)
    return deleted


def cleanup_orphaned_teams(db: Session, apply: bool = False) -> dict:
    teams = find_orphaned_teams(db)
    reports = []
    totals = {'teams_found': len(teams), 'teams_deleted': 0, 'teams_archived': 0, 'published_schedule_records_preserved': 0}
    try:
        for team in teams:
            published_refs = _published_reference_count(db, team.id)
            action = 'would_delete' if not published_refs else 'would_archive'
            reason = None
            if published_refs:
                reason = 'Permanent deletion blocked because published schedule/score/tournament records reference this live team.'
                totals['published_schedule_records_preserved'] += published_refs
            report = OrphanedTeamReport(str(team.id), team.name, _division_label(team), _season_names(db, team.id), str(team.organization_id), action if not apply else action.replace('would_', ''))
            report.reason = reason
            reports.append(asdict(report))
            if apply:
                if published_refs:
                    team.is_active = False
                    totals['teams_archived'] += 1
                else:
                    _delete_unpublished_team_dependencies(db, team.id)
                    db.delete(team)
                    totals['teams_deleted'] += 1
        if apply:
            db.commit()
        else:
            db.rollback()
        return {'dry_run': not apply, 'reports': reports, 'totals': totals}
    except Exception:
        db.rollback()
        raise
