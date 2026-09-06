"""Dependency-light guardrails for the shared field-layout boundary."""
import ast
from pathlib import Path


APP = Path(__file__).parents[1] / 'app'


def _qualified_calls(path):
    tree = ast.parse(path.read_text())
    return {
        f'{node.func.value.id}.{node.func.attr}'
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }


def test_import_preview_and_publish_use_authoritative_validator():
    shared_call = 'facility_layout_validation.validate_field_configuration'

    assert shared_call in _qualified_calls(APP / 'services' / 'schedule_import.py')
    assert shared_call in _qualified_calls(APP / 'routes' / 'api.py')


def test_import_commit_revalidates_before_schedule_mutation():
    source = (APP / 'routes' / 'api.py').read_text()
    validation = source.index(
        'facility_layout_validation.validate_field_configuration',
        source.index('def confirm_schedule_import'),
    )
    mutation = source.index('db.query(Game).filter(', validation)

    assert validation < mutation


def test_legacy_evaluator_name_is_only_a_compatibility_alias():
    module = ast.parse((APP / 'services' / 'facility_layout_validation.py').read_text())
    evaluator_definitions = [
        node for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == 'evaluate_host_timeslot_capacity'
    ]
    aliases = [
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name)
                and target.id == 'evaluate_host_timeslot_capacity'
                for target in node.targets)
    ]

    assert evaluator_definitions == []
    assert len(aliases) == 1
