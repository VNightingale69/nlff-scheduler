"""Audit and conservatively repair persisted host-layout memberships."""
from collections import Counter, defaultdict

from app.models import Field, FieldConfigurationMember, HostLocationConfiguration


SIZES = ('SMALL', 'MEDIUM', 'LARGE')


def _normalized_name(value):
    return ' '.join(str(value or '').strip().casefold().split())


def audit_host_configurations(db, host_location_id, scheduled_field_ids=()):
    """Return reusable, ID-based integrity diagnostics for one host.

    Names are used only to identify duplicate/obsolete legacy records. They are
    never returned as layout compatibility evidence.
    """
    fields = db.query(Field).filter(Field.host_location_id == host_location_id).all()
    active_fields = [field for field in fields if field.is_active and field.deleted_at is None]
    by_name = defaultdict(list)
    for field in fields:
        by_name[_normalized_name(field.name)].append(field)
    duplicates = [group for group in by_name.values() if len(group) > 1]
    configurations = db.query(HostLocationConfiguration).filter(
        HostLocationConfiguration.host_location_id == host_location_id,
        HostLocationConfiguration.is_active.is_(True),
    ).all()
    zero_members = []
    deleted_members = []
    cross_host_members = []
    obsolete_members = []
    covered = set()
    details = []
    for configuration in configurations:
        members = list(configuration.members or [])
        if not members:
            zero_members.append(configuration.id)
        valid_ids = []
        for member in members:
            field = member.field
            if not field or not field.is_active or field.deleted_at is not None:
                deleted_members.append(member.id)
                obsolete_members.append(member.id)
            elif field.host_location_id != host_location_id:
                cross_host_members.append(member.id)
            else:
                valid_ids.append(field.id)
                covered.add(field.id)
        details.append({'configuration_id': configuration.id,
                        'configuration_name': configuration.configuration_name,
                        'field_ids': valid_ids})
    scheduled = set(scheduled_field_ids or ())
    return {
        'host_location_id': host_location_id,
        'active_field_count': len(active_fields),
        'active_configuration_count': len(configurations),
        'zero_member_configuration_ids': zero_members,
        'deleted_member_ids': deleted_members,
        'cross_host_member_ids': cross_host_members,
        'obsolete_member_ids': obsolete_members,
        'duplicate_fields': [[field.id for field in group] for group in duplicates],
        'uncovered_scheduled_field_ids': sorted(scheduled - covered, key=str),
        'configurations': details,
    }


def repair_host_configuration_memberships(db, host_location_id):
    """Repair only relationships whose canonical replacement is unambiguous.

    Stale members may move to the sole active same-host field with the same
    normalized legacy label. Empty legacy layouts are reconstructed only when
    their persisted size counts describe the host's *entire* active inventory
    for every required size. Ambiguous layouts are deliberately unchanged.
    """
    fields = db.query(Field).filter(Field.host_location_id == host_location_id).all()
    active = [field for field in fields if field.is_active and field.deleted_at is None]
    active_by_name = defaultdict(list)
    active_by_size = defaultdict(list)
    for field in active:
        active_by_name[_normalized_name(field.name)].append(field)
        active_by_size[str(field.layout_type or '').strip().upper()].append(field)

    repaired = 0
    changes = []
    configurations = db.query(HostLocationConfiguration).filter(
        HostLocationConfiguration.host_location_id == host_location_id,
        HostLocationConfiguration.is_active.is_(True),
    ).all()
    for configuration in configurations:
        before = [member.field_id for member in configuration.members]
        for member in list(configuration.members):
            field = member.field
            if field and field.host_location_id == host_location_id and field.is_active and field.deleted_at is None:
                continue
            candidates = active_by_name.get(_normalized_name(field.name if field else None), [])
            if len(candidates) == 1 and not any(row.field_id == candidates[0].id for row in configuration.members):
                member.field = candidates[0]
                repaired += 1

        if not configuration.members:
            expected = Counter({size: int(getattr(configuration, f'{size.lower()}_field_count', 0) or 0)
                                for size in SIZES})
            required_sizes = [size for size in SIZES if expected[size]]
            # Exact cardinality makes the persisted legacy definition a unique
            # mapping. A host with extra same-size fields requires admin input.
            if required_sizes and all(len(active_by_size[size]) == expected[size] for size in required_sizes):
                selected = [field for size in required_sizes for field in active_by_size[size]]
                configuration.members[:] = [FieldConfigurationMember(field=field) for field in selected]
                repaired += len(selected)
        after = [member.field_id or (member.field.id if member.field else None) for member in configuration.members]
        if before != after:
            changes.append({'configuration_id': configuration.id,
                            'configuration_name': configuration.configuration_name,
                            'before': before, 'after': after})
    db.flush()
    return {'memberships_repaired': repaired, 'changes': changes,
            'audit': audit_host_configurations(db, host_location_id)}
