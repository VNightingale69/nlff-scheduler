"""Authoritative division choices for current and historical operations."""

import uuid

from sqlalchemy.orm import Query, Session

from app.models import Division, Game, Season, Team


def division_reference_query(db: Session, season_id: uuid.UUID | None = None) -> Query:
    """Return divisions valid for the requested scheduling context.

    Active seasons use the configured active league divisions, including before a
    schedule has games.  An inactive (historical) season instead derives its
    divisions from the games preserved in that season, so retired labels remain
    available without becoming current scheduling choices.
    """
    season = (
        db.query(Season).filter(Season.id == season_id).first()
        if season_id
        else db.query(Season).filter(Season.is_active.is_(True)).order_by(Season.start_date.desc()).first()
    )

    if season_id and season is None:
        return db.query(Division).filter(False)
    if season is None or season.is_active:
        return db.query(Division).filter(Division.is_active.is_(True))

    home_divisions = db.query(Team.division_id).join(Game, Game.home_team_id == Team.id).filter(Game.season_id == season.id)
    away_divisions = db.query(Team.division_id).join(Game, Game.away_team_id == Team.id).filter(Game.season_id == season.id)
    historical_division_ids = home_divisions.union(away_divisions).subquery()
    return (
        db.query(Division)
        .filter(Division.id.in_(db.query(historical_division_ids.c.division_id)))
    )
