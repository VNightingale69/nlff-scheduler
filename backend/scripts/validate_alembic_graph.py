#!/usr/bin/env python3
"""Fail when Alembic revisions are duplicated, broken, or have multiple heads."""

from __future__ import annotations

import ast
from pathlib import Path


VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def literal_assignment(tree: ast.Module, name: str, path: Path):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            value = node.value
        else:
            continue
        try:
            return ast.literal_eval(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path}: {name} must be a literal") from exc
    raise ValueError(f"{path}: missing {name} assignment")


def main() -> int:
    revisions: dict[str, Path] = {}
    parents: dict[str, tuple[str, ...]] = {}
    errors: list[str] = []

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        try:
            revision = literal_assignment(tree, "revision", path)
            down_revision = literal_assignment(tree, "down_revision", path)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        if not isinstance(revision, str) or not revision:
            errors.append(f"{path}: revision must be a non-empty string")
            continue
        if revision in revisions:
            errors.append(
                f"duplicate revision {revision!r}: {revisions[revision]} and {path}"
            )
        else:
            revisions[revision] = path

        if down_revision is None:
            parents[revision] = ()
        elif isinstance(down_revision, str):
            parents[revision] = (down_revision,)
        elif isinstance(down_revision, (tuple, list)) and all(
            isinstance(parent, str) for parent in down_revision
        ):
            parents[revision] = tuple(down_revision)
        else:
            errors.append(f"{path}: invalid down_revision {down_revision!r}")

    referenced = {parent for values in parents.values() for parent in values}
    for revision, values in parents.items():
        for parent in values:
            if parent not in revisions:
                errors.append(
                    f"{revisions[revision]}: down_revision {parent!r} does not exist"
                )

    heads = sorted(set(revisions) - referenced)
    if len(heads) != 1:
        errors.append(f"expected exactly one Alembic head, found {len(heads)}: {heads}")

    if errors:
        print("Alembic graph validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Alembic graph valid: {len(revisions)} unique revisions; head={heads[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
