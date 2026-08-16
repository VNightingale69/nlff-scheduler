"""Canonical eligibility rules for teams in the current season configuration."""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Query

from app.models import Division, Game, Organization, OrganizationDivisionParticipation, Season, Team

logger = logging.getLogger(__name__)


def normalize_team_identity(value: object) -> str:
    """Normalize harmless formatting differences without fuzzy matching."""
    return re.sub(r'[^a-z0-9]', '', str(value or '').strip().casefold())


def canonical_division_name(division: Division) -> str:
    return f'{division.division_group or ""} {division.name}'.strip()


def canonical_team_display_name(team: Team) -> str:
    """Build the spreadsheet-facing name from canonical relationships."""
    return f'{team.organization.name} {canonical_division_name(team.division)} {team_specific_name(team)}'.strip()


def _identity_tokens(value: object) -> list[str]:
    return re.findall(r'[a-z0-9]+', str(value or '').strip().casefold())


def _suffix_after(tokens: list[str], prefix: list[str]) -> list[str] | None:
    if tokens[:len(prefix)] == prefix:
        return tokens[len(prefix):]
    return None


def team_specific_name(team: Team) -> str:
    """Return the team-specific portion of either short or legacy display names.

    Most records store a color (for example ``Black``).  Some legacy records
    store an already-rendered name such as ``J’Burg Coed K-1 Black``.  Division
    is a canonical relationship, so the text following its token sequence is
    the stable team-specific identifier in both representations.
    """
    tokens = _identity_tokens(team.name)
    division_tokens = _identity_tokens(canonical_division_name(team.division))
    for index in range(len(tokens) - len(division_tokens) + 1):
        if tokens[index:index + len(division_tokens)] == division_tokens:
            suffix = tokens[index + len(division_tokens):]
            if suffix:
                return ' '.join(suffix)
    return team.name.strip()


@dataclass(frozen=True)
class TeamResolution:
    team: Team | None
    community: str | None
    team_name: str | None
    candidate_count: int = 0


def resolve_roster_team(teams: list[Team], division: Division | None, imported_name: object) -> TeamResolution:
    """Resolve one active roster record by display name, then structured identity."""
    if division is None:
        return TeamResolution(None, None, None)
    value_key = normalize_team_identity(imported_name)
    division_teams = [team for team in teams if team.division_id == division.id]

    exact = [team for team in division_teams
             if value_key in {normalize_team_identity(team.name),
                              normalize_team_identity(canonical_team_display_name(team))}]
    if len(exact) == 1:
        return TeamResolution(exact[0], exact[0].organization.name, team_specific_name(exact[0]), 1)
    if len(exact) > 1:
        return TeamResolution(None, None, None, len(exact))

    imported_tokens = _identity_tokens(imported_name)
    division_tokens = _identity_tokens(canonical_division_name(division))
    parsed = []
    for team in division_teams:
        community_tokens = _identity_tokens(team.organization.name)
        remainder = _suffix_after(imported_tokens, community_tokens)
        if remainder is None:
            continue
        specific_tokens = _suffix_after(remainder, division_tokens)
        if not specific_tokens:
            continue
        parsed.append((team.organization, ' '.join(specific_tokens)))

    parsed_identities = {(organization.id, normalize_team_identity(specific))
                         for organization, specific in parsed}
    # A division's display punctuation (and, historically, its terminal grade)
    # is not part of a team's identity.  Once the caller has resolved the
    # configured Division relationship, allow an exact community prefix and
    # team-specific suffix to bridge legacy division labels such as
    # ``Coed 6, 7, 8`` and the canonical import label ``Coed 6-7``.  Both ends
    # must be exact and the result must be unique; this never searches another
    # division.
    if not parsed_identities:
        structured = []
        for team in division_teams:
            community_tokens = _identity_tokens(team.organization.name)
            specific_tokens = _identity_tokens(team_specific_name(team))
            if (imported_tokens[:len(community_tokens)] == community_tokens
                    and specific_tokens
                    and imported_tokens[-len(specific_tokens):] == specific_tokens
                    and len(imported_tokens) > len(community_tokens) + len(specific_tokens)):
                structured.append(team)
        identities = {(team.organization_id, normalize_team_identity(team_specific_name(team)))
                      for team in structured}
        if len(structured) == 1 and len(identities) == 1:
            team = structured[0]
            return TeamResolution(team, team.organization.name, team_specific_name(team), 1)
        if len(structured) > 1:
            return TeamResolution(None, None, None, len(structured))
    if len(parsed_identities) != 1:
        return TeamResolution(None, None, None)
    organization_id, specific_key = parsed_identities.pop()
    community = next(organization.name for organization, _ in parsed if organization.id == organization_id)
    specific = next(specific for organization, specific in parsed if organization.id == organization_id)
    matches = [team for team in division_teams
               if team.organization_id == organization_id
               and normalize_team_identity(team_specific_name(team)) == specific_key]
    return TeamResolution(matches[0] if len(matches) == 1 else None, community, specific, len(matches))


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
