"""Canonical eligibility rules for teams in the current season configuration."""

import logging
import uuid

from sqlalchemy.orm import Query

from app.models import Division, Game, Organization, OrganizationDivisionParticipation, Season, Team

logger = logging.getLogger(__name__)


def eligible_team_query(query: Query) -> Query:
    """Limit a Team query to teams eligible for current-season team screens.

    Organization/division participation is the application's current-season
    assignment.  Games and schedules are deliberately not consulted: they are
    historical records and must not make a removed team current again.
    """
    return (
        query
        .join(Organization, Team.organization_id == Organization.id)
        .join(Division, Team.division_id == Division.id)
        .join(
            OrganizationDivisionParticipation,
            (OrganizationDivisionParticipation.organization_id == Team.organization_id)
            & (OrganizationDivisionParticipation.division_id == Team.division_id),
        )
        .filter(
            Team.is_active.is_(True),
            Team.deleted_at.is_(None),
            Team.superseded_by_team_id.is_(None),
            Organization.is_active.is_(True),
            Organization.deleted_at.is_(None),
            Division.is_active.is_(True),
            OrganizationDivisionParticipation.is_active.is_(True),
            OrganizationDivisionParticipation.is_participating.is_(True),
            OrganizationDivisionParticipation.team_count > 0,
        )
    )


def season_roster_query(db, season_id: uuid.UUID | str | None = None) -> Query:
    """Return the single authoritative scheduling/admin team population.

    Team membership is represented by the current organization/division
    participation configuration (there is intentionally no season_id column on
    Team).  ``season_id`` documents and validates the requested scheduling
    scope; historical Game rows are never allowed to resurrect a team.
    """
    if season_id is not None:
        # Evaluate this independently rather than joining games: a new season has
        # a roster before it has a schedule run or any Game rows.
        db.query(Season.id).filter(Season.id == season_id).first()
    return eligible_team_query(db.query(Team))


def season_roster(db, season_id: uuid.UUID | str | None = None) -> list[Team]:
    return season_roster_query(db, season_id).order_by(Team.name, Team.id).all()


def log_schedule_roster_exclusions(db, season_id: uuid.UUID | str | None = None) -> list[dict[str, object]]:
    """Log records a legacy readiness/schedule-run query would over-count."""
    authoritative_ids = {team.id for team in season_roster(db, season_id)}
    legacy_rows = db.query(Team).join(Division, Team.division_id == Division.id).filter(
        Team.is_active.is_(True), Division.is_active.is_(True)
    ).all()
    excluded = []
    for team in legacy_rows:
        if team.id in authoritative_ids:
            continue
        participation = db.query(OrganizationDivisionParticipation).filter(
            OrganizationDivisionParticipation.organization_id == team.organization_id,
            OrganizationDivisionParticipation.division_id == team.division_id,
        ).first()
        game_seasons = [str(value) for (value,) in db.query(Game.season_id).filter(
            (Game.home_team_id == team.id) | (Game.away_team_id == team.id)
        ).distinct().all() if value]
        detail = {
            'team_id': str(team.id), 'team_name': team.name,
            'division_id': str(team.division_id),
            'division_name': team.division.name if team.division else None,
            'is_active': team.is_active, 'deleted_at': str(team.deleted_at) if team.deleted_at else None,
            'superseded_by_team_id': str(team.superseded_by_team_id) if team.superseded_by_team_id else None,
            'requested_season_id': str(season_id) if season_id else None,
            'schedule_game_season_ids': game_seasons,
            'participation_active': participation.is_active if participation else None,
            'is_participating': participation.is_participating if participation else None,
            'participation_team_count': participation.team_count if participation else None,
        }
        excluded.append(detail)
        logger.warning('schedule_roster_record_excluded %s', detail)
    return excluded
