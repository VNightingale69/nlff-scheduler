import re

from sqlalchemy import and_

from app.models import Organization


def normalize_organization_name(name: str | None) -> str:
    """Normalize organization/community names for duplicate and seed checks."""
    return re.sub(r'\s+', ' ', (name or '').strip()).casefold()


def active_organization_filter():
    return and_(Organization.is_active.is_(True), Organization.deleted_at.is_(None))
