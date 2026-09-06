"""Resolve and validate supported facility layouts for scheduled kickoff waves."""
from collections import Counter
from dataclasses import dataclass, field as dataclass_field
import logging
import re

from sqlalchemy.orm import selectinload

from app.models import (Field, FieldConfigurationMember, FieldPhysicalConflict,
                        HostLocation, HostLocationConfiguration, TimeslotFieldConfiguration)
from app.turf_configurations import APPROVED_TURF_CONFIGURATIONS, turf_configuration_counts


SIZES = ('SMALL', 'MEDIUM', 'LARGE')
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedConfigurationField:
    """One canonical playable position in a persisted facility layout."""
    configuration_field_id: object
    field_id: object
    name: str
    field_type: str | None
    physical_area_id: object | None


@dataclass(frozen=True)
class ResolvedFacilityConfiguration:
    """Shared preview/persistence representation of a facility layout.

    Generated slots, hosting rows, and physical-area joins are deliberately
    diagnostics rather than playable positions.  Capacity is based only on
    canonical configuration-member identities.
    """
    facility_id: object
    facility_name: str
    configuration_id: object
    configuration_code: str
    logical_fields: tuple[ResolvedConfigurationField, ...]
    physical_area_ids: tuple[object, ...] = dataclass_field(default_factory=tuple)
    legacy_field_ids: tuple[object, ...] = dataclass_field(default_factory=tuple)
    generated_slot_ids: tuple[object, ...] = dataclass_field(default_factory=tuple)


def resolve_facility_configuration(configuration, site):
    """Resolve canonical logical fields once, independent of derived rows."""
    seen = set()
    logical_fields = []
    for member in list(getattr(configuration, 'members', ()) or ()):
        # The member/slot identity is canonical. Repeated ORM rows must never
        # turn one playable field into extra capacity.
        identity = member.field_id
        if identity in seen:
            continue
        seen.add(identity)
        playable = member.field
        logical_fields.append(ResolvedConfigurationField(
            configuration_field_id=member.id,
            field_id=member.field_id,
            name=getattr(playable, 'name', ''),
            field_type=_size(getattr(playable, 'layout_type', None)),
            physical_area_id=getattr(playable, 'physical_field_area_id', None),
        ))
    return ResolvedFacilityConfiguration(
        facility_id=site.id,
        facility_name=site.name,
        configuration_id=configuration.id,
        configuration_code=configuration.configuration_name,
        logical_fields=tuple(logical_fields),
        physical_area_ids=tuple(dict.fromkeys(
            item.physical_area_id for item in logical_fields if item.physical_area_id)),
        legacy_field_ids=tuple(item.field_id for item in logical_fields),
    )


def log_configuration_integrity_failure(resolved, expected_count, reason):
    logger.error(
        'facility_configuration_integrity_failure facility_id=%s facility_name=%s '
        'configuration_id=%s configuration_code=%s expected_logical_field_count=%s '
        'resolved_logical_field_count=%s configuration_field_ids=%s field_ids=%s '
        'field_names=%s physical_area_ids=%s legacy_field_ids=%s generated_slot_ids=%s reason=%s',
        resolved.facility_id, resolved.facility_name, resolved.configuration_id,
        resolved.configuration_code, expected_count, len(resolved.logical_fields),
        [str(item.configuration_field_id) for item in resolved.logical_fields],
        [str(item.field_id) for item in resolved.logical_fields],
        [item.name for item in resolved.logical_fields],
        [str(value) for value in resolved.physical_area_ids],
        [str(value) for value in resolved.legacy_field_ids],
        [str(value) for value in resolved.generated_slot_ids], reason,
    )


def _size(value):
    value = str(value or '').strip().upper()
    return value if value in SIZES else None


def _capacity(configuration):
    capacity = {size: int(getattr(configuration, f'{size.lower()}_field_count', 0) or 0) for size in SIZES}
    if any(capacity.values()):
        return capacity
    # Capacity columns were added after the first custom configurations. Keep
    # those rows usable by normalizing their human/code labels once here.
    label = str(getattr(configuration, 'configuration_name', '') or '').strip().upper()
    words = {'ONE': 1, 'TWO': 2, 'THREE': 3, 'FOUR': 4}
    tokens = re.findall(r'[A-Z]+|\d+', label)
    for index, token in enumerate(tokens[:-1]):
        size = tokens[index + 1]
        if size in SIZES and (token.isdigit() or token in words):
            capacity[size] += int(token) if token.isdigit() else words[token]
    return capacity


def configuration_supports_field_types(configuration, field_types):
    """Return whether one layout can accommodate the complete typed wave.

    Configuration members describe the canonical positions used to build a
    layout; they are not an allow-list of numbered physical fields.  Runtime
    assignments therefore match the layout's normalized type capacities.
    """
    demand = Counter(filter(None, (_size(value) for value in field_types)))
    capacity = _capacity(configuration)
    return bool(demand) and all(demand[size] <= capacity[size] for size in SIZES)


def choose_supported_configuration(configurations, field_types, previous_code=None):
    """Choose a deterministic containing layout for one complete wave."""
    demand = Counter(filter(None, (_size(value) for value in field_types)))
    supported = [item for item in configurations
                 if configuration_supports_field_types(item, field_types)]
    if not supported:
        return None
    demand_exact = {size: int(demand.get(size, 0)) for size in SIZES}
    demand_total = sum(demand_exact.values())
    return min(supported, key=lambda item: (
        0 if _capacity(item) == demand_exact else 1,
        sum(_capacity(item)[size] for size in SIZES if not demand_exact[size]),
        sum(_capacity(item).values()) - demand_total,
        0 if item.configuration_name == previous_code else 1,
        item.configuration_name,
    ))


def supported_configurations_for_fields(db, host_id, field_ids):
    """Resolve active physical fields to layouts by type and capacity.

    The original sequence is retained long enough to reject duplicate use of
    one physical field.  Only after that identity check do normalized field
    types determine which facility configurations can support the wave.
    """
    assigned = [value for value in field_ids if value]
    if len(assigned) != len(set(assigned)):
        return [], 'A physical field is assigned more than once at this date and kickoff.'
    fields = db.query(Field).filter(Field.id.in_(assigned)).all() if assigned else []
    by_id = {item.id: item for item in fields}
    if any(value not in by_id for value in assigned) or any(
        item.host_location_id != host_id or not item.is_active or item.deleted_at is not None
        for item in fields
    ):
        return [], 'Assigned fields do not belong to this host or are inactive.'
    field_types = [by_id[value].layout_type for value in assigned]
    configurations = get_active_supported_layouts(db, host_id)
    return [item for item in configurations
            if configuration_supports_field_types(item, field_types)], None


def active_supported_layouts_query(db, host_location_id):
    """Build the uncached authoritative query shared by API and schedulers."""
    return (
        db.query(HostLocationConfiguration)
        .options(
            selectinload(HostLocationConfiguration.members)
            .selectinload(FieldConfigurationMember.field)
        )
        .filter(
            HostLocationConfiguration.host_location_id == host_location_id,
            HostLocationConfiguration.is_active.is_(True),
        )
    )


def get_active_supported_layouts(db, host_location_id):
    """Load every current alternative layout for one host location.

    League-approved definitions are authoritative for managed turf stadiums;
    persisted configurations remain authoritative for other facility types.
    This intentionally does not inspect generated slots, turf waves, or a
    default timeslot selection. Persisted members and fields are eagerly loaded.
    """
    host = db.query(HostLocation).filter(HostLocation.id == host_location_id).first()
    if host and (host.surface_type or '').upper() == 'TURF_STADIUM':
        # Approved layouts describe capability when a site has not persisted a
        # decision for that layout yet.  A persisted inactive row is an
        # explicit retirement, however, and must never be resurrected merely
        # because its code is in the approved catalog.
        existing = {
            str(row.configuration_name or '').strip().upper(): row
            for row in db.query(HostLocationConfiguration).filter(
                HostLocationConfiguration.host_location_id == host_location_id,
            ).all()
        }
        layouts = []
        for sort_order, metadata in enumerate(APPROVED_TURF_CONFIGURATIONS):
            code = str(metadata['code'])
            persisted = existing.get(code)
            if persisted is not None and not persisted.is_active:
                continue
            configuration = persisted or HostLocationConfiguration(
                host_location_id=host_location_id,
                configuration_name=code,
                is_active=True,
            )
            counts = turf_configuration_counts(metadata)
            configuration.small_field_count = counts['SMALL']
            configuration.medium_field_count = counts['MEDIUM']
            configuration.large_field_count = counts['LARGE']
            configuration.sort_order = sort_order
            layouts.append(configuration)
        return layouts
    return (
        active_supported_layouts_query(db, host_location_id)
        .order_by(
            HostLocationConfiguration.sort_order,
            HostLocationConfiguration.configuration_name,
            HostLocationConfiguration.id,
        )
        .all()
    )


def validate_timeslot_demands(demands, available_layouts):
    """Validate physical capacity independently for every host kickoff wave.

    ``demands`` maps ``(date, host, kickoff)`` to size counts and
    ``available_layouts`` maps the same key to one or more allowed capacity
    dictionaries.  A later kickoff is deliberately a different key, so the
    same physical field can be reused.  A wave is valid only when one complete
    allowed layout can accommodate its simultaneous combination.
    """
    shortages = []
    peak = {size: 0 for size in SIZES}
    for key, raw_demand in demands.items():
        demand = {size: int(raw_demand.get(size, 0) or 0) for size in SIZES}
        for size in SIZES:
            peak[size] = max(peak[size], demand[size])
        layouts = [
            {size: int(layout.get(size, 0) or 0) for size in SIZES}
            for layout in available_layouts.get(key, [])
        ]
        if any(all(layout[size] >= demand[size] for size in SIZES) for layout in layouts):
            continue
        best = max(layouts, key=lambda layout: sum(min(layout[size], demand[size]) for size in SIZES), default={size: 0 for size in SIZES})
        individually_supported = bool(layouts) and all(
            max((layout[size] for layout in layouts), default=0) >= demand[size] for size in SIZES
        )
        shortages.append({
            'key': key,
            'demand': demand,
            'available_layouts': layouts,
            'shortage_by_size': {size: max(demand[size] - best.get(size, 0), 0) for size in SIZES},
            'unsupported_combination': individually_supported,
        })
    return {'valid': not shortages, 'peak_by_size': peak, 'shortages': shortages}


def select_supported_layout(db, host_id, game_date, kickoff, required_sizes, *, persist=False):
    """Select one explicitly configured layout satisfying the whole wave.

    Considering all games together is what makes a one-Large layout consume
    both logical Medium positions instead of merely changing one field label.
    """
    demand = Counter(filter(None, (_size(value) for value in required_sizes)))
    existing = db.query(TimeslotFieldConfiguration).filter_by(
        host_location_id=host_id, configuration_date=game_date, kickoff_time=kickoff,
    ).first()
    configurations = get_active_supported_layouts(db, host_id)
    supported = [configuration for configuration in configurations
                 if validate_timeslot_demands(
                     {(game_date, host_id, kickoff): demand},
                     {(game_date, host_id, kickoff): [_capacity(configuration)]},
                 )['valid']]
    if existing:
        selected = next((item for item in configurations if item.id == existing.configuration_id), None)
        if selected:
            # An active, time-specific row is an explicit physical-layout lock.
            # It is the only case where one layout may conclusively block a
            # wave.  A row pointing to a retired layout is historical generated
            # metadata, however, and must not hide current alternatives.
            return existing, selected, selected in supported
    if not supported:
        return None, None, False
    previous_code = None
    if game_date is not None and kickoff is not None:
        previous = (
            db.query(TimeslotFieldConfiguration)
            .join(HostLocationConfiguration)
            .filter(
                TimeslotFieldConfiguration.host_location_id == host_id,
                TimeslotFieldConfiguration.configuration_date == game_date,
                TimeslotFieldConfiguration.kickoff_time < kickoff,
                HostLocationConfiguration.is_active.is_(True),
            )
            .order_by(TimeslotFieldConfiguration.kickoff_time.desc())
            .first()
        )
        if previous and previous.configuration:
            previous_code = previous.configuration.configuration_name

    selected = choose_supported_configuration(supported, required_sizes, previous_code)
    override = None
    if persist and selected.id is not None:
        if existing:
            existing.configuration_id = selected.id
            override = existing
        else:
            override = TimeslotFieldConfiguration(host_location_id=host_id, configuration_id=selected.id,
                                                  configuration_date=game_date, kickoff_time=kickoff)
            db.add(override)
        db.flush()
    return override, selected, True


def active_layout_capacities(db, host_id):
    """Return the current host-scoped layouts considered by validation."""
    configurations = get_active_supported_layouts(db, host_id)
    return [
        {'id': str(configuration.id) if configuration.id else None, 'code': configuration.configuration_name, 'capacity': _capacity(configuration)}
        for configuration in configurations
    ]


def layout_label(configuration):
    if not configuration:
        return None
    parts = [f'{count} {size.title()}' for size, count in _capacity(configuration).items() if count]
    return ' + '.join(parts) or configuration.configuration_name


def validate_field_combination(db, host_id, field_ids):
    """Return whether canonical physical fields can operate simultaneously.

    Configured hosts resolve layouts by normalized type capacity, while the
    original field IDs still enforce host ownership, duplicate assignments,
    and explicit physical-conflict relationships. Hosts with no configuration
    records retain the legacy active-field fallback.
    """
    assigned = [field_id for field_id in field_ids if field_id]
    used = set(assigned)
    matching, resolution_error = supported_configurations_for_fields(db, host_id, assigned)
    if resolution_error:
        return False, [item.configuration_name for item in get_active_supported_layouts(db, host_id)], used
    # Membership provides the configuration fast path, including at facilities
    # that also use synthetic turf capacity layouts.
    configurations = active_supported_layouts_query(db, host_id).order_by(
        HostLocationConfiguration.sort_order,
        HostLocationConfiguration.configuration_name,
    ).all()
    layouts = []
    for configuration in configurations:
        members = {
            row.field_id
            for row in db.query(FieldConfigurationMember)
            .join(Field, Field.id == FieldConfigurationMember.field_id)
            .filter(
                FieldConfigurationMember.field_configuration_id == configuration.id,
                Field.host_location_id == host_id,
                Field.is_active.is_(True),
                Field.deleted_at.is_(None),
            )
        }
        if members:
            layouts.append((configuration, members))
    # An active empty configuration is an error, not permission for every
    # active field to operate together. Preserve the fallback only for hosts
    # that have never adopted the configuration table.
    if not configurations:
        active = {
            row.id
            for row in db.query(Field.id).filter(
                Field.host_location_id == host_id,
                Field.is_active.is_(True),
                Field.deleted_at.is_(None),
            )
        }
        if not matching:
            return used.issubset(active), [], active
    if configurations and not layouts:
        return False, [configuration.configuration_name for configuration in configurations], used
    names = [configuration.configuration_name for configuration in configurations]
    active = {
        row.id for row in db.query(Field.id).filter(
            Field.host_location_id == host_id, Field.is_active.is_(True), Field.deleted_at.is_(None),
        )
    }
    if not used.issubset(active):
        return False, names, used
    conflicts = db.query(FieldPhysicalConflict.id).filter(
        FieldPhysicalConflict.host_location_id == host_id,
        FieldPhysicalConflict.field_a_id.in_(used),
        FieldPhysicalConflict.field_b_id.in_(used),
    ).first()
    # A named layout is evidence that the combination is supported, but it is
    # not a prerequisite for ordinary, independently playable fields.  The
    # explicit physical-conflict table is the authoritative restriction for a
    # combination assembled from fields in different named layouts.
    return conflicts is None, names, used


def fields_can_operate_simultaneously(db, host_id, field_ids):
    """Return host ownership/activity and explicit pairwise overlap diagnostics."""
    used = {value for value in field_ids if value}
    fields = db.query(Field).filter(Field.id.in_(used)).all() if used else []
    by_id = {field.id: field for field in fields}
    invalid_ids = sorted(str(value) for value in used if (
        value not in by_id or by_id[value].host_location_id != host_id
        or not by_id[value].is_active or by_id[value].deleted_at is not None
    ))
    pairs = []
    if not invalid_ids:
        relationships = db.query(FieldPhysicalConflict).filter(
            FieldPhysicalConflict.host_location_id == host_id,
            FieldPhysicalConflict.field_a_id.in_(used),
            FieldPhysicalConflict.field_b_id.in_(used),
        ).all()
        for relationship in relationships:
            first, second = by_id[relationship.field_a_id], by_id[relationship.field_b_id]
            pairs.append({'field_a_id': str(first.id), 'field_a': first.name,
                          'field_b_id': str(second.id), 'field_b': second.name,
                          'reason': relationship.reason or 'Fields occupy overlapping physical field space.'})
    invalid_reason = ('Assigned field IDs do not belong to this host or are inactive: '
                      + ', '.join(invalid_ids)) if invalid_ids else None
    return {'valid': not invalid_ids and not pairs,
            'assigned_fields': [by_id[value].name for value in used if value in by_id],
            'invalid_field_ids': invalid_ids, 'conflicting_pairs': pairs,
            'reason': (invalid_reason if invalid_ids else
                       'Physical field conflicts found.' if pairs else 'No physical field conflicts.')}


def field_combination_diagnostics(db, host_id, field_ids, required_field_types=()):
    """Describe the persisted, host-ID-scoped membership decision."""
    assigned = [field_id for field_id in field_ids if field_id]
    used = set(assigned)
    matching, resolution_error = supported_configurations_for_fields(db, host_id, assigned)
    matching_codes = {item.configuration_name for item in matching}
    required_types = list(required_field_types or ())
    evaluations = []
    matching_name = None
    configurations = active_supported_layouts_query(db, host_id).order_by(
        HostLocationConfiguration.sort_order,
        HostLocationConfiguration.configuration_name,
    ).all()
    for configuration in configurations:
        fields = (
            db.query(Field)
            .join(FieldConfigurationMember, FieldConfigurationMember.field_id == Field.id)
            .filter(
                FieldConfigurationMember.field_configuration_id == configuration.id,
                Field.host_location_id == host_id,
                Field.is_active.is_(True),
                Field.deleted_at.is_(None),
            )
            .order_by(Field.name)
            .all()
        )
        member_ids = {field.id for field in fields}
        # A configuration member identifies a physical position.  Its base
        # ``layout_type`` describes the position's default use, not every use
        # supported by an alternate layout.  For example, the same two turf
        # positions can be two Medium fields in one layout and one Large plus
        # one Small in another.  Match stable member IDs first, then validate
        # the wave's required logical sizes against that configuration.
        member_match = bool(used) and used.issubset(member_ids)
        capacity_match = (configuration_supports_field_types(configuration, required_types)
                          if required_types else configuration.configuration_name in matching_codes)
        compatible = member_match and capacity_match
        if compatible and matching_name is None:
            matching_name = configuration.configuration_name
        evaluations.append({
            'id': str(configuration.id) if configuration.id else None,
            'name': configuration.configuration_name,
            'field_ids': [str(field.id) for field in fields],
            'fields': [field.name for field in fields],
            'is_active': bool(configuration.is_active),
            'member_match': member_match,
            'capacity_match': capacity_match,
            'status': 'VALID' if compatible else ('ACTIVE BUT INVALID' if not member_ids else 'INCOMPATIBLE'),
            'reason': (resolution_error if resolution_error else
                       'Configuration contains no assigned physical fields.' if not member_ids else None),
        })
    referenced = {value for evaluation in evaluations for value in evaluation['field_ids']}
    unreferenced = [str(value) for value in used if str(value) not in referenced]
    return {'configurations': evaluations, 'compatible_configuration': matching_name,
            'unreferenced_assigned_field_ids': sorted(unreferenced)}


def evaluate_host_timeslot_capacity(db, host_location_id, game_date, kickoff_time, scheduled_games):
    """Evaluate one saved-game wave against physical field membership.

    ``scheduled_games`` is a sequence of mappings containing ``field_id`` and
    ``required_field_size`` (and, optionally, display labels).  Stable saved
    field IDs are authoritative.  Configuration quantity columns are only a
    fallback for legacy assignments which have no canonical physical field.
    This keeps generated slots and their historical configuration selection
    out of publication decisions.
    """
    games = list(scheduled_games)
    field_ids = [game.get('field_id') for game in games if game.get('field_id')]
    assigned_fields = [game.get('field_name') for game in games if game.get('field_name')]
    required = Counter(filter(None, (_size(game.get('required_field_size')) for game in games)))
    required_counts = {size: int(required.get(size, 0)) for size in SIZES}
    capacities = active_layout_capacities(db, host_location_id)
    membership = field_combination_diagnostics(
        db, host_location_id, field_ids,
        [game.get('required_field_size') for game in games],
    ) if field_ids else {
        'configurations': [], 'compatible_configuration': None,
    }

    # If every saved game resolves to a physical field, compatibility is a
    # resource-membership question, not a comparison of size-count labels.
    if games and len(field_ids) == len(games):
        valid, supported, _used = validate_field_combination(db, host_location_id, field_ids)
        physical = fields_can_operate_simultaneously(db, host_location_id, field_ids)
        fields = db.query(Field).filter(Field.id.in_(field_ids)).all()
        assigned_counts = Counter(
            filter(None, (_size(field.layout_type) for field in fields))
        )
        shortages = {
            size: required_counts[size] - int(assigned_counts.get(size, 0))
            for size in SIZES
            if int(assigned_counts.get(size, 0)) < required_counts[size]
        }
        named_configuration_valid = bool(membership['compatible_configuration'])
        # Raw field types are defaults for a physical position.  They must not
        # veto an active named reconfiguration whose member IDs and logical
        # capacity both match this complete wave.
        if shortages and not named_configuration_valid:
            details = ', '.join(
                f"insufficient {size.title()} fields (required {required_counts[size]}, "
                f"assigned {int(assigned_counts.get(size, 0))})"
                for size in SIZES if size in shortages
            )
            physical = {**physical, 'valid': False, 'reason': details}
            valid = False
        if len(field_ids) != len(set(field_ids)):
            physical = {**physical, 'valid': False,
                        'reason': 'A physical field is assigned more than once at this date and kickoff.'}
            valid = False
        if named_configuration_valid and len(field_ids) == len(set(field_ids)):
            valid = True
            physical = {**physical, 'valid': True, 'reason': 'No physical field conflicts.',
                        'conflicting_pairs': []}
        issue_code = None if valid else 'FIELD_LAYOUT_CONFLICT'
        # The blocker and diagnostics deliberately project this one reason;
        # never label the absence of physical conflicts as an invalid reason.
        conflict_reason = physical['reason']
        if not valid and conflict_reason == 'No physical field conflicts.':
            conflict_reason = 'Assigned fields do not form a valid active physical layout.'
        if physical['conflicting_pairs']:
            conflict_reason = '; '.join(
                f"{pair['field_a']} and {pair['field_b']} cannot operate simultaneously: {pair['reason']}"
                for pair in physical['conflicting_pairs'])
        blocking_issues = [] if valid else [{
            'issue_code': issue_code,
            'reason': conflict_reason,
            'conflicting_fields': assigned_fields,
        }]
        result = {
            'valid': valid,
            'issue_code': issue_code,
            'blocking_issues': blocking_issues,
            'assigned_field_ids': [str(value) for value in field_ids],
            'assigned_fields': assigned_fields,
            'required_field_sizes': required_counts,
            'compatible_configuration': membership['compatible_configuration'],
            'is_valid': valid,
            'is_blocking': not valid,
            'validation_method': ('named_configuration' if named_configuration_valid
                                  else 'physical_field_compatibility'),
            'host_location_id': str(host_location_id),
            'configuration_id': next((row['id'] for row in membership['configurations']
                                      if row['name'] == membership['compatible_configuration']), None),
            'configuration_name': membership['compatible_configuration'],
            'conflicts': physical['conflicting_pairs'],
            'warnings': [],
            'active_configurations': membership['configurations'],
            'available_layouts': capacities,
            'conflicting_fields': sorted({name for pair in physical['conflicting_pairs'] for name in (pair['field_a'], pair['field_b'])}),
            'conflicting_pairs': physical['conflicting_pairs'],
            'reason': (('Assigned physical fields coexist in the persisted configuration.'
                        if membership['compatible_configuration'] else 'No physical field conflicts.') if valid else conflict_reason),
            'configuration_basis': ('Named configuration membership (field IDs)' if membership['compatible_configuration']
                                    else 'Physical field compatibility (field IDs)'),
            'supported_layouts': supported,
        }
        assert not result['valid'] or not result['blocking_issues']
        return result

    result = validate_timeslot_demands(
        {(game_date, host_location_id, kickoff_time): required_counts},
        {(game_date, host_location_id, kickoff_time): [row['capacity'] for row in capacities]},
    )
    valid = result['valid']
    issue_code = None if valid else ('HOST_TIMESLOT_CAPACITY_SHORTAGE' if capacities else
                                     'HOST_TIMESLOT_CONFIGURATION_UNCONFIRMED')
    blocking_issues = [] if valid or not capacities else [{
        'issue_code': issue_code,
        'reason': 'Canonical physical field assignments are missing and no active layout has sufficient capacity.',
        'conflicting_fields': [],
    }]
    result = {
        'valid': valid,
        'issue_code': issue_code,
        'blocking_issues': blocking_issues,
        'assigned_field_ids': [str(value) for value in field_ids],
        'assigned_fields': assigned_fields,
        'required_field_sizes': required_counts,
        'compatible_configuration': None,
        'active_configurations': membership['configurations'],
        'available_layouts': capacities,
        'conflicting_fields': [],
        'reason': ('Legacy assignments fit an active host configuration.' if valid else
                   'Canonical physical field assignments are missing and no active layout has sufficient capacity.'),
        'configuration_basis': 'Active configuration capacity fallback (missing physical field IDs)',
        'supported_layouts': [row['code'] for row in capacities],
    }
    assert not result['valid'] or not result['blocking_issues']
    return result
