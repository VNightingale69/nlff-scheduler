"""Site-scoped resolution of human-readable field identifiers."""

import re

from sqlalchemy.orm import Session

from app.models import Field, HostLocation


_CANONICAL_COMPONENT_SEPARATOR = re.compile(r'\s+(?:-|\u2013|\u2014)\s+')


def normalize_field_identifier(value: object) -> str:
    """Normalize harmless presentation differences without fuzzy matching."""
    text = str(value or '').strip().casefold()
    text = re.sub(r'[._/]+', ' ', text)
    return re.sub(r'\s+', ' ', text)


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
