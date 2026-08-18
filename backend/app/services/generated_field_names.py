"""Persistence and presentation helpers for generated field instance names."""

import re
from typing import Protocol


RETIRED_GENERATED_FIELD_PREFIX = "__retired_generated__"
_RETIRED_GENERATED_FIELD_WRAPPER = re.compile(
    rf"^{re.escape(RETIRED_GENERATED_FIELD_PREFIX)}(?P<token>[A-Za-z0-9-]+)__(?P<name>.+)$",
    re.DOTALL,
)
_ADJACENT_RETIRED_GENERATED_FIELD_WRAPPER = re.compile(
    r"^retired_generated__(?P<token>[A-Za-z0-9-]+)__(?P<name>.+)$",
    re.DOTALL,
)
_PUBLIC_INTERNAL_FIELD_MARKER = re.compile(
    r"(?:__generated__|__retired_generated__|(?:^|_)retired_(?:$|_))",
    re.IGNORECASE,
)


class GeneratedField(Protocol):
    id: object
    field_name: str
    is_active: bool


def get_original_generated_field_name(name: str | None) -> str:
    """Remove every valid, leading retirement wrapper from a stored name.

    Repeated matching is intentional: older regeneration runs could retire the
    same referenced instance more than once.  Anchoring and validating the
    token prevents ordinary field names containing the marker from changing.
    """
    original = str(name or "")
    match = _RETIRED_GENERATED_FIELD_WRAPPER.fullmatch(original)
    if not match:
        return original
    original = match.group("name")
    # Adjacent wrappers share the two underscores between the outer wrapper's
    # delimiter and the inner marker.  Historical values therefore continue
    # with ``retired_generated__`` rather than a second literal leading ``__``.
    while match := (
        _RETIRED_GENERATED_FIELD_WRAPPER.fullmatch(original)
        or _ADJACENT_RETIRED_GENERATED_FIELD_WRAPPER.fullmatch(original)
    ):
        original = match.group("name")
    return original


def is_retired_generated_field(field_or_name: GeneratedField | str | None) -> bool:
    name = field_or_name if isinstance(field_or_name, str) else getattr(field_or_name, "field_name", None)
    return bool(_RETIRED_GENERATED_FIELD_WRAPPER.fullmatch(str(name or "")))


def get_field_display_name(field_or_name: GeneratedField | str | None) -> str:
    name = field_or_name if isinstance(field_or_name, str) else getattr(field_or_name, "field_name", None)
    return get_original_generated_field_name(name)


def get_public_field_display_name(field_or_name: GeneratedField | str | None) -> str | None:
    """Return a safe public label, or no label when only internal data exists.

    Known retirement wrappers are decoded structurally first.  Any remaining
    lifecycle marker means the value is malformed or is not a display label;
    callers must fall back to another canonical source rather than leaking it.
    """
    display_name = get_field_display_name(field_or_name).strip()
    if not display_name or _PUBLIC_INTERNAL_FIELD_MARKER.search(display_name):
        return None
    return display_name


def retire_generated_field(field: GeneratedField) -> bool:
    """Retire a generated field once while retaining its stable database ID."""
    changed = False
    if not is_retired_generated_field(field):
        field.field_name = (
            f"{RETIRED_GENERATED_FIELD_PREFIX}{str(field.id)[:8]}__{field.field_name}"
        )[:120]
        changed = True
    field.is_active = False
    return changed
