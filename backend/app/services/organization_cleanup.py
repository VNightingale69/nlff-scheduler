import logging
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Field, FieldConfigurationOption, FieldInstance, Game, GameSlot, HostLocation, HostingAvailability, Organization, OrganizationDivisionParticipation, PhysicalFieldArea, Team

logger = logging.getLogger(__name__)


class OrganizationCleanupError(Exception):
    pass


@dataclass(frozen=True)
class CleanupStep:
    key: str
    model: type
    query_builder: callable


CLEANUP_STEPS = [
    CleanupStep('games', Game, lambda db, org_id: db.query(Game).filter((Game.home_team_id.in_(db.query(Team.id).filter(Team.organization_id == org_id).subquery())) | (Game.away_team_id.in_(db.query(Team.id).filter(Team.organization_id == org_id).subquery())))),
    CleanupStep('game_slots', GameSlot, lambda db, org_id: db.query(GameSlot).filter(GameSlot.host_location_id.in_(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).subquery()))),
    CleanupStep('field_instances', FieldInstance, lambda db, org_id: db.query(FieldInstance).filter(FieldInstance.host_location_id.in_(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).subquery()))),
    CleanupStep('hosting_availabilities', HostingAvailability, lambda db, org_id: db.query(HostingAvailability).filter((HostingAvailability.field_id.in_(db.query(Field.id).filter(Field.host_location_id.in_(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).subquery())).subquery())) | (HostingAvailability.physical_field_area_id.in_(db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id.in_(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).subquery())).subquery())))),
    CleanupStep('field_configuration_options', FieldConfigurationOption, lambda db, org_id: db.query(FieldConfigurationOption).filter(FieldConfigurationOption.physical_field_area_id.in_(db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id.in_(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).subquery())).subquery()))),
    CleanupStep('physical_field_areas', PhysicalFieldArea, lambda db, org_id: db.query(PhysicalFieldArea).filter(PhysicalFieldArea.host_location_id.in_(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).subquery()))),
    CleanupStep('fields', Field, lambda db, org_id: db.query(Field).filter(Field.host_location_id.in_(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id).subquery()))),
    CleanupStep('host_locations', HostLocation, lambda db, org_id: db.query(HostLocation).filter(HostLocation.organization_id == org_id)),
    CleanupStep('teams', Team, lambda db, org_id: db.query(Team).filter(Team.organization_id == org_id)),
    CleanupStep('organization_division_participations', OrganizationDivisionParticipation, lambda db, org_id: db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.organization_id == org_id)),
    CleanupStep('organization', Organization, lambda db, org_id: db.query(Organization).filter(Organization.id == org_id)),
]


def cleanup_organization_dependencies(db: Session, org_id: uuid.UUID, dry_run: bool = False) -> dict:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail='Organization not found')

    counts: dict[str, int] = {}
    try:
        for step in CLEANUP_STEPS:
            q = step.query_builder(db, org_id)
            counts[step.key] = q.count()
            logger.info('[ORG DELETE] organization_id=%s organization_name=%s step=%s dry_run=%s count=%s', org_id, org.name, step.key, dry_run, counts[step.key])
            if not dry_run:
                q.delete(synchronize_session=False)
        if dry_run:
            db.rollback()
            return {'success': True, 'dry_run': True, 'organization_id': str(org_id), 'would_delete': counts}
        db.commit()
        return {'success': True, 'dry_run': False, 'organization_id': str(org_id), 'deleted': counts}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception('Organization dependency cleanup failed for org_id=%s', org_id)
        raise HTTPException(status_code=500, detail={'error': 'organization_delete_failed', 'message': 'Unable to delete organization because dependent records could not be cleaned up. No data was deleted.'})
    except Exception:
        db.rollback()
        logger.exception('Organization cleanup failed unexpectedly for org_id=%s', org_id)
        raise HTTPException(status_code=500, detail={'error': 'organization_delete_failed', 'message': 'Organization deletion failed unexpectedly. No data was deleted.'})
