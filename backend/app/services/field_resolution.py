"""Scheduling lookups and lifecycle-independent historical game display."""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Field, FieldInstance, Game, GameSlot, HostLocation
from app.services.generated_field_names import get_field_display_name


_CANONICAL_COMPONENT_SEPARATOR = re.compile(r'\s+(?:-|\u2013|\u2014)\s+')


def normalize_field_identifier(value: object) -> str:
    """Normalize harmless presentation differences without fuzzy matching."""
    text = str(value or '').strip().casefold()
    text = re.sub(r'[._/]+', ' ', text)
    # A separator hyphen in a display label is optional (``Medium - 1``,
    # ``Medium-1`` and ``Medium 1`` identify the same field).  This deliberately
    # does not remove letters or digits, so sizes and field numbers can never
    # drift into one another as they could with fuzzy matching.
    text = re.sub(r'\s*[-\u2013\u2014]\s*', ' ', text)
    return re.sub(r'\s+', ' ', text)


def resolve_legacy_import_field(db: Session, site: HostLocation,
                                physical_area_value: object,
                                field_value: object) -> Field | None:
    """Resolve a flat-field import using deterministic source precedence.

    Legacy workbooks may put the schedulable field in the newer Physical Area
    column.  Exact canonical labels from that column win, followed by exact
    labels from Field, then the same two columns under safe normalization.
    Every step requires a unique active, site-scoped match.
    """
    fields = db.query(Field).filter(
        Field.host_location_id == site.id,
        Field.is_active.is_(True),
        Field.deleted_at.is_(None),
    ).all()
    values = (physical_area_value, field_value)
    for value in values:
        requested = str(value or '').strip().casefold()
        if not requested:
            continue
        matches = [item for item in fields
                   if str(item.name or '').strip().casefold() == requested]
        if len(matches) == 1:
            return matches[0]
    for value in values:
        requested = normalize_field_identifier(value)
        if not requested:
            continue
        matches = [item for item in fields
                   if normalize_field_identifier(item.name) == requested]
        if len(matches) == 1:
            return matches[0]
    return None


def logical_field_identifiers(field: Field) -> set[str]:
    """Return explicit aliases, or a deterministic canonical-name suffix.

    ``Field`` currently stores only ``name``.  The attribute checks make this
    resolver reusable if a structured field label is added later, without
    creating import-only field data.
    """
    identifiers = set()
    for attribute in ('short_name', 'label', 'field_number', 'position', 'display_name'):
        value = getattr(field, attribute, None)
        if value not in (None, ''):
            identifiers.add(normalize_field_identifier(value))
    if identifiers:
        return identifiers

    components = _CANONICAL_COMPONENT_SEPARATOR.split(str(field.name or '').strip())
    if len(components) > 1 and components[-1].strip():
        identifiers.add(normalize_field_identifier(components[-1]))
    return identifiers


def resolve_active_field(db: Session, site: HostLocation, identifier: object) -> Field | None:
    """Resolve one canonical active field within ``site``, or return ``None``.

    Exact canonical names take precedence.  Logical identifiers are accepted
    only when exactly one active field at the resolved site matches.
    """
    requested = normalize_field_identifier(identifier)
    if not requested:
        return None
    fields = db.query(Field).filter(
        Field.host_location_id == site.id,
        Field.is_active.is_(True),
        Field.deleted_at.is_(None),
    ).all()
    canonical = [field for field in fields if normalize_field_identifier(field.name) == requested]
    if len(canonical) == 1:
        return canonical[0]
    logical = [field for field in fields if requested in logical_field_identifiers(field)]
    return logical[0] if len(logical) == 1 else None


@dataclass(frozen=True)
class HistoricalFieldDisplay:
    """A display value plus the stable historical source that supplied it."""

    name: str | None
    source: str
    field_id: object | None = None
    field_instance_id: object | None = None
    physical_area_name: str | None = None


def resolve_game_field_display(
    game: Game,
    db: Session | None = None,
    *,
    generated_slot: GameSlot | None = None,
    field_instance: FieldInstance | None = None,
) -> HistoricalFieldDisplay:
    """Resolve an assigned game's field without applying schedulability rules.

    This is deliberately separate from :func:`resolve_active_field`.  Stable
    IDs on old games remain readable even when their rows are inactive,
    retired, or soft-deleted.  Snapshots are evidence of last resort, never an
    identity that can be selected for a new game.
    """
    instance = field_instance or getattr(generated_slot, 'field_instance', None)
    if instance is None:
        instance = getattr(game, 'field_instance', None)
    instance_id = (
        getattr(generated_slot, 'field_instance_id', None)
        or getattr(game, 'field_instance_id', None)
    )
    if instance is None and db is not None and instance_id:
        instance = db.get(FieldInstance, instance_id)
    if instance is not None:
        name = get_field_display_name(getattr(instance, 'field_name', None))
        if name:
            return HistoricalFieldDisplay(name, 'generated_slot' if generated_slot else 'field_instance',
                                          field_instance_id=getattr(instance, 'id', instance_id))

    field_id = getattr(game, 'field_id', None)
    field = getattr(game, 'field', None)
    if field is None and db is not None and field_id:
        # db.get intentionally has no active/deleted predicate.
        field = db.get(Field, field_id)
    if field is not None:
        name = get_field_display_name(getattr(field, 'name', None))
        area = getattr(field, 'physical_field_area', None)
        if name:
            return HistoricalFieldDisplay(name, 'field', field_id=getattr(field, 'id', field_id),
                                          physical_area_name=getattr(area, 'name', None))

    snapshot = getattr(game, 'field_display_name_snapshot', None) or getattr(game, 'previous_field_name', None)
    snapshot = get_field_display_name(snapshot)
    if snapshot:
        return HistoricalFieldDisplay(snapshot, 'snapshot', field_id=field_id or getattr(game, 'previous_field_id', None),
                                      physical_area_name=getattr(game, 'physical_area_name_snapshot', None))
    return HistoricalFieldDisplay(None, 'unassigned')


def snapshot_game_field_display(game: Game, resolved: HistoricalFieldDisplay, host_name: str | None = None) -> None:
    """Persist durable display evidence without changing scheduling identity."""
    if resolved.name and not getattr(game, 'field_display_name_snapshot', None):
        game.field_display_name_snapshot = resolved.name
    if resolved.physical_area_name and not getattr(game, 'physical_area_name_snapshot', None):
        game.physical_area_name_snapshot = resolved.physical_area_name
    if host_name and not getattr(game, 'host_location_name_snapshot', None):
        game.host_location_name_snapshot = host_name
