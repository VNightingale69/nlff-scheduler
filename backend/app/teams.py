"""Canonical eligibility rules for teams in the current league configuration."""

from sqlalchemy.orm import Query

from app.models import Division, Organization, OrganizationDivisionParticipation, Team


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
