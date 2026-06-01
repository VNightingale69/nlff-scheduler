import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import inspect, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import ROLE_LEAGUE_ADMIN
from app.database import Base
from app.models import (
    Field,
    FieldConfigurationOption,
    FieldInstance,
    Game,
    GameSlot,
    HostLocation,
    HostLocationConfiguration,
    HostPlanSelection,
    HostingAvailability,
    Organization,
    OrganizationDivisionParticipation,
    PhysicalFieldArea,
    Role,
    Team,
    TurfWave,
    User,
)

logger = logging.getLogger(__name__)


class OrganizationCleanupError(Exception):
    pass


@dataclass(frozen=True)
class DependentForeignKey:
    table: str
    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    constraint: str
    ondelete: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            'table': self.table,
            'columns': list(self.columns),
            'referred_table': self.referred_table,
            'referred_columns': list(self.referred_columns),
            'constraint': self.constraint,
            'ondelete': self.ondelete,
        }


ORGANIZATION_DELETE_TARGET_TABLES = {
    'organizations',
    'host_locations',
    'fields',
    'teams',
    'generated_slots',
    'game_slots',
    'games',
    'hosting_availabilities',
    'physical_field_areas',
    'field_configuration_options',
    'field_instances',
    'turf_waves',
    'host_location_configurations',
}


CONSTRAINT_DETAIL_RE = re.compile(r'(?:constraint|foreign key constraint) ["\']?([^"\'\s]+)["\']?', re.IGNORECASE)
TABLE_DETAIL_RE = re.compile(r'(?:on|from) table ["\']?([^"\'\s]+)["\']?', re.IGNORECASE)


def _unique(values: Iterable[uuid.UUID | None]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    result: list[uuid.UUID] = []
    for value in values:
        if value is None or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _ids(query) -> list[uuid.UUID]:
    return _unique(value for (value,) in query.all())


def _delete_by_ids(db: Session, model: type, ids: list[uuid.UUID]) -> int:
    if not ids:
        return 0
    return db.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)


def _metadata_dependent_foreign_keys() -> list[DependentForeignKey]:
    foreign_keys: list[DependentForeignKey] = []
    for table in Base.metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            if not elements:
                continue
            referred_table = elements[0].column.table.name
            if referred_table not in ORGANIZATION_DELETE_TARGET_TABLES:
                continue
            foreign_keys.append(
                DependentForeignKey(
                    table=table.name,
                    columns=tuple(element.parent.name for element in elements),
                    referred_table=referred_table,
                    referred_columns=tuple(element.column.name for element in elements),
                    constraint=constraint.name or _fallback_constraint_name(table.name, tuple(element.parent.name for element in elements), referred_table),
                    ondelete=elements[0].ondelete,
                )
            )
    return sorted(foreign_keys, key=lambda fk: (fk.referred_table, fk.table, fk.columns))


def _database_dependent_foreign_keys(db: Session) -> list[DependentForeignKey]:
    """Return DB-reflected FKs when available, falling back to SQLAlchemy metadata in tests/offline mode."""
    try:
        inspector = inspect(db.bind)
        table_names = set(inspector.get_table_names())
        foreign_keys: list[DependentForeignKey] = []
        for table_name in sorted(table_names):
            for fk in inspector.get_foreign_keys(table_name):
                referred_table = fk.get('referred_table')
                if referred_table not in ORGANIZATION_DELETE_TARGET_TABLES:
                    continue
                columns = tuple(fk.get('constrained_columns') or [])
                referred_columns = tuple(fk.get('referred_columns') or [])
                foreign_keys.append(
                    DependentForeignKey(
                        table=table_name,
                        columns=columns,
                        referred_table=str(referred_table),
                        referred_columns=referred_columns,
                        constraint=fk.get('name') or _fallback_constraint_name(table_name, columns, str(referred_table)),
                        ondelete=(fk.get('options') or {}).get('ondelete'),
                    )
                )
        return sorted(foreign_keys, key=lambda fk: (fk.referred_table, fk.table, fk.columns))
    except Exception:
        logger.exception('Unable to inspect database foreign keys for organization delete; using model metadata')
        return _metadata_dependent_foreign_keys()


def _fallback_constraint_name(table: str, columns: tuple[str, ...], referred_table: str) -> str:
    column_part = '_'.join(columns) if columns else 'fk'
    return f'{table}_{column_part}_{referred_table}_fkey'


def _foreign_key_catalog_for_log(db: Session) -> list[dict[str, object]]:
    return [fk.as_dict() for fk in _database_dependent_foreign_keys(db)]


def _extract_blocking_dependency(exc: SQLAlchemyError, db: Session) -> dict[str, str | None]:
    orig = getattr(exc, 'orig', None)
    diag = getattr(orig, 'diag', None)
    constraint = getattr(diag, 'constraint_name', None) if diag is not None else None
    table = getattr(diag, 'table_name', None) if diag is not None else None
    message = str(orig or exc)

    if constraint is None:
        match = CONSTRAINT_DETAIL_RE.search(message)
        if match:
            constraint = match.group(1)
    if table is None:
        match = TABLE_DETAIL_RE.search(message)
        if match:
            table = match.group(1)

    for fk in _database_dependent_foreign_keys(db):
        if constraint and fk.constraint == constraint:
            table = table or fk.table
            return {
                'table': fk.table,
                'constraint': fk.constraint,
                'columns': ','.join(fk.columns),
                'referred_table': fk.referred_table,
                'message': message,
            }
        if table and fk.table == table:
            return {
                'table': fk.table,
                'constraint': fk.constraint,
                'columns': ','.join(fk.columns),
                'referred_table': fk.referred_table,
                'message': message,
            }

    return {'table': table, 'constraint': constraint, 'columns': None, 'referred_table': None, 'message': message}


def _blocked_delete_http_error(org_id: uuid.UUID, exc: SQLAlchemyError, db: Session) -> HTTPException:
    blocker = _extract_blocking_dependency(exc, db)
    table = blocker.get('table') or 'unknown table'
    constraint = blocker.get('constraint') or 'unknown constraint'
    message = f'Unable to delete organization because {table}.{constraint} blocked deletion. No data was deleted.'
    logger.exception(
        'Organization dependency cleanup failed for org_id=%s blocked_table=%s blocked_constraint=%s blocked_columns=%s referred_table=%s',
        org_id,
        blocker.get('table'),
        blocker.get('constraint'),
        blocker.get('columns'),
        blocker.get('referred_table'),
    )
    return HTTPException(
        status_code=500,
        detail={
            'error': 'organization_delete_failed',
            'message': message,
            'blocked_table': blocker.get('table'),
            'blocked_constraint': blocker.get('constraint'),
            'blocked_columns': blocker.get('columns'),
            'blocked_referred_table': blocker.get('referred_table'),
        },
    )


def collect_organization_delete_inventory(db: Session, org_id: uuid.UUID) -> dict[str, object]:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail='Organization not found')

    team_ids = _ids(db.query(Team.id).filter(Team.organization_id == org_id))
    host_location_ids = _ids(db.query(HostLocation.id).filter(HostLocation.organization_id == org_id))
    field_ids = _ids(db.query(Field.id).filter(Field.host_location_id.in_(host_location_ids))) if host_location_ids else []
    area_ids = _ids(db.query(PhysicalFieldArea.id).filter(PhysicalFieldArea.host_location_id.in_(host_location_ids))) if host_location_ids else []
    configuration_ids = _ids(db.query(HostLocationConfiguration.id).filter(HostLocationConfiguration.host_location_id.in_(host_location_ids))) if host_location_ids else []
    field_configuration_option_ids = _ids(db.query(FieldConfigurationOption.id).filter(FieldConfigurationOption.physical_field_area_id.in_(area_ids))) if area_ids else []

    availability_filters = [HostingAvailability.organization_id == org_id]
    if host_location_ids:
        availability_filters.append(HostingAvailability.host_location_id.in_(host_location_ids))
    if field_ids:
        availability_filters.append(HostingAvailability.field_id.in_(field_ids))
    if area_ids:
        availability_filters.append(HostingAvailability.physical_field_area_id.in_(area_ids))
    if configuration_ids:
        availability_filters.append(HostingAvailability.selected_configuration_id.in_(configuration_ids))
    if field_configuration_option_ids:
        availability_filters.append(HostingAvailability.field_configuration_option_id.in_(field_configuration_option_ids))
    availability_ids = _ids(db.query(HostingAvailability.id).filter(or_(*availability_filters)))

    field_instance_filters = []
    if host_location_ids:
        field_instance_filters.append(FieldInstance.host_location_id.in_(host_location_ids))
    if availability_ids:
        field_instance_filters.append(FieldInstance.hosting_availability_id.in_(availability_ids))
    field_instance_ids = _ids(db.query(FieldInstance.id).filter(or_(*field_instance_filters))) if field_instance_filters else []

    turf_wave_filters = []
    if host_location_ids:
        turf_wave_filters.append(TurfWave.host_location_id.in_(host_location_ids))
    if availability_ids:
        turf_wave_filters.append(TurfWave.hosting_availability_id.in_(availability_ids))
    turf_wave_ids = _ids(db.query(TurfWave.id).filter(or_(*turf_wave_filters))) if turf_wave_filters else []

    game_filters = []
    if team_ids:
        game_filters.extend([Game.home_team_id.in_(team_ids), Game.away_team_id.in_(team_ids)])
    if field_ids:
        game_filters.append(Game.field_id.in_(field_ids))
    if host_location_ids:
        game_filters.append(Game.host_location_id.in_(host_location_ids))
    if field_instance_ids:
        game_filters.append(Game.field_instance_id.in_(field_instance_ids))
    game_ids = _ids(db.query(Game.id).filter(or_(*game_filters))) if game_filters else []

    game_slot_filters = []
    if field_instance_ids:
        game_slot_filters.append(GameSlot.field_instance_id.in_(field_instance_ids))
    if host_location_ids:
        game_slot_filters.append(GameSlot.host_location_id.in_(host_location_ids))
    if game_ids:
        game_slot_filters.append(GameSlot.assigned_game_id.in_(game_ids))
    if turf_wave_ids:
        game_slot_filters.append(GameSlot.turf_wave_id.in_(turf_wave_ids))
    game_slot_ids = _ids(db.query(GameSlot.id).filter(or_(*game_slot_filters))) if game_slot_filters else []

    host_plan_selection_filters = [HostPlanSelection.community_id == org_id]
    if host_location_ids:
        host_plan_selection_filters.append(HostPlanSelection.host_location_id.in_(host_location_ids))
    if availability_ids:
        host_plan_selection_filters.append(HostPlanSelection.availability_id.in_(availability_ids))
    host_plan_selection_ids = _ids(db.query(HostPlanSelection.id).filter(or_(*host_plan_selection_filters)))

    league_admin_role_ids = _ids(db.query(Role.id).filter(Role.name.in_([ROLE_LEAGUE_ADMIN, 'league_admin'])))
    user_query = db.query(User.id).outerjoin(Role, User.role_id == Role.id).filter(User.organization_id == org_id)
    # The schema has a single optional organization assignment. Global league admins have no organization_id and are not matched here;
    # league admins explicitly assigned to this organization are matched and deleted with other organization-scoped users.
    user_ids = _ids(user_query)
    global_league_admins_preserved = db.query(User).filter(User.organization_id.is_(None), User.role_id.in_(league_admin_role_ids)).count() if league_admin_role_ids else 0

    participation_ids = _ids(db.query(OrganizationDivisionParticipation.id).filter(OrganizationDivisionParticipation.organization_id == org_id))

    ids_by_key = {
        'game_slots': game_slot_ids,
        'generated_slots': game_slot_ids,
        'games': game_ids,
        'host_plan_selections': host_plan_selection_ids,
        'turf_waves': turf_wave_ids,
        'field_instances': field_instance_ids,
        'hosting_availabilities': availability_ids,
        'field_configuration_options': field_configuration_option_ids,
        'fields': field_ids,
        'host_location_configurations': configuration_ids,
        'physical_field_areas': area_ids,
        'host_locations': host_location_ids,
        'teams': team_ids,
        'organization_division_participations': participation_ids,
        'users': user_ids,
        'organizations': [org_id],
    }
    counts = {key: len(value) for key, value in ids_by_key.items()}
    counts['global_league_admins_preserved'] = global_league_admins_preserved
    return {'organization': org, 'ids': ids_by_key, 'counts': counts}


def cleanup_organization_dependencies(db: Session, org_id: uuid.UUID, dry_run: bool = False) -> dict:
    try:
        inventory = collect_organization_delete_inventory(db, org_id)
        org = inventory['organization']
        organization_id = str(org.id)
        organization_name = org.name
        ids_by_key = inventory['ids']
        counts = inventory['counts']
        dependent_foreign_keys = _foreign_key_catalog_for_log(db)

        logger.info(
            '[ORG DELETE] organization_id=%s organization_name=%s dry_run=%s counts=%s dependent_foreign_keys=%s',
            org_id,
            org.name,
            dry_run,
            counts,
            dependent_foreign_keys,
        )
        if dry_run:
            db.rollback()
            return {
                'success': True,
                'dry_run': True,
                'organization_id': organization_id,
                'organization_name': organization_name,
                'would_delete': counts,
                'dependent_foreign_keys': dependent_foreign_keys,
            }

        deleted: dict[str, int] = {}
        # Delete child/schedule rows first so every FK is cleared before parent rows are removed.
        # Order matters: game_slots bridges games/field_instances/turf_waves, so remove it before all three parents.
        deleted['game_slots'] = _delete_by_ids(db, GameSlot, ids_by_key['game_slots'])
        deleted['generated_slots'] = deleted['game_slots']
        deleted['games'] = _delete_by_ids(db, Game, ids_by_key['games'])
        deleted['host_plan_selections'] = _delete_by_ids(db, HostPlanSelection, ids_by_key['host_plan_selections'])
        deleted['turf_waves'] = _delete_by_ids(db, TurfWave, ids_by_key['turf_waves'])
        deleted['field_instances'] = _delete_by_ids(db, FieldInstance, ids_by_key['field_instances'])
        deleted['hosting_availabilities'] = _delete_by_ids(db, HostingAvailability, ids_by_key['hosting_availabilities'])
        deleted['field_configuration_options'] = _delete_by_ids(db, FieldConfigurationOption, ids_by_key['field_configuration_options'])
        deleted['fields'] = _delete_by_ids(db, Field, ids_by_key['fields'])
        deleted['host_location_configurations'] = _delete_by_ids(db, HostLocationConfiguration, ids_by_key['host_location_configurations'])
        deleted['physical_field_areas'] = _delete_by_ids(db, PhysicalFieldArea, ids_by_key['physical_field_areas'])
        deleted['organization_division_participations'] = _delete_by_ids(db, OrganizationDivisionParticipation, ids_by_key['organization_division_participations'])
        deleted['teams'] = _delete_by_ids(db, Team, ids_by_key['teams'])
        deleted['users'] = _delete_by_ids(db, User, ids_by_key['users'])
        deleted['host_locations'] = _delete_by_ids(db, HostLocation, ids_by_key['host_locations'])
        deleted['organizations'] = _delete_by_ids(db, Organization, ids_by_key['organizations'])
        deleted['global_league_admins_preserved'] = counts['global_league_admins_preserved']

        db.commit()
        return {
            'success': True,
            'dry_run': False,
            'organization_id': organization_id,
            'organization_name': organization_name,
            'counts': counts,
            'deleted': deleted,
            'dependent_foreign_keys': dependent_foreign_keys,
        }
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise _blocked_delete_http_error(org_id, exc, db) from exc
    except Exception:
        db.rollback()
        logger.exception('Organization cleanup failed unexpectedly for org_id=%s', org_id)
        raise HTTPException(status_code=500, detail={'error': 'organization_delete_failed', 'message': 'Organization deletion failed unexpectedly. No data was deleted.'})
