from types import SimpleNamespace

import pytest

from app.services.division_field_types import required_field_type_for_division


@pytest.mark.parametrize(('group', 'name', 'expected'), [
    ('Coed', 'K-1', 'SMALL'),
    ('Coed', '2-3', 'SMALL'),
    ('Coed', '4-5', 'MEDIUM'),
    ('Coed', '6-7', 'LARGE'),
    ('Girls', '3-5', 'MEDIUM'),
    ('Girls', '6-8', 'LARGE'),
])
def test_canonical_flag_division_field_type_fallback(group, name, expected):
    division = SimpleNamespace(division_group=group, name=name, required_field_layout_type=None)
    assert required_field_type_for_division(division) == expected


def test_configured_league_rule_is_authoritative():
    division = SimpleNamespace(division_group='Coed', name='6-7', required_field_layout_type='MEDIUM')
    assert required_field_type_for_division(division) == 'MEDIUM'
