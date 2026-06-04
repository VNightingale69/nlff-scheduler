import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / 'app'


def _literal_string_set(node: ast.AST) -> set[str]:
    if not isinstance(node, (ast.Dict, ast.Set, ast.Tuple, ast.List)):
        return set()
    values = node.keys if isinstance(node, ast.Dict) else node.elts
    return {item.value for item in values if isinstance(item, ast.Constant) and isinstance(item.value, str)}


def _assigned_node(module: ast.Module, name: str) -> ast.AST:
    for node in module.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    raise AssertionError(f'{name} assignment not found')


def test_turf_stadium_configurations_are_limited_to_approved_wave_codes():
    module = ast.parse((APP_ROOT / 'turf_configurations.py').read_text())
    configs = _assigned_node(module, 'APPROVED_TURF_CONFIGURATIONS')
    assert isinstance(configs, ast.Tuple)
    codes = set()
    for item in configs.elts:
        assert isinstance(item, ast.Dict)
        for key, value in zip(item.keys, item.values):
            if isinstance(key, ast.Constant) and key.value == 'code':
                assert isinstance(value, ast.Constant)
                codes.add(value.value)

    assert codes == {
        'THREE_SMALL',
        'TWO_SMALL_ONE_MEDIUM',
        'TWO_MEDIUM',
        'ONE_SMALL_ONE_LARGE',
    }
    assert 'TWO_LARGE' not in codes
    assert 'ONE_LARGE_ONE_MEDIUM' not in codes
    assert 'ONE_MEDIUM_ONE_SMALL' not in codes


def test_manual_turf_validation_slot_counts_match_approved_wave_codes_only():
    module = ast.parse((APP_ROOT / 'services' / 'scheduling_validation.py').read_text())
    layouts = _assigned_node(module, 'TURF_APPROVED_LAYOUTS_BY_SMALL_MEDIUM_LARGE')
    assert isinstance(layouts, ast.Dict)
    code_values = {value.value for value in layouts.values if isinstance(value, ast.Constant)}
    count_keys = {tuple(item.value for item in key.elts) for key in layouts.keys if isinstance(key, ast.Tuple)}

    assert code_values == {
        'THREE_SMALL',
        'TWO_SMALL_ONE_MEDIUM',
        'TWO_MEDIUM',
        'ONE_SMALL_ONE_LARGE',
    }
    assert count_keys == {(3, 0, 0), (2, 1, 0), (0, 2, 0), (1, 0, 1)}
