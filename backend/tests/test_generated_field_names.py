import unittest
import uuid
from types import SimpleNamespace

from app.routes.api import _field_export_display_label
from app.services.generated_field_names import (
    get_field_display_name,
    get_public_field_display_name,
    get_original_generated_field_name,
    is_retired_generated_field,
    retire_generated_field,
)


class GeneratedFieldNamesTest(unittest.TestCase):
    def test_retired_generated_field_display_name_strips_single_prefix(self):
        self.assertEqual(get_field_display_name('__retired_generated__abc123__Medium Field 1'), 'Medium Field 1')

    def test_hiller_duplicate_retirement_prefix_regressions(self):
        cases = {
            '__retired_generated__f9ac615f__retired_generated__f9ac615f__Medium Field 1': 'Medium Field 1',
            '__retired_generated__ac5628a3__retired_generated__ac5628a3__Medium Field 2': 'Medium Field 2',
        }
        for stored_name, display_name in cases.items():
            self.assertEqual(get_field_display_name(stored_name), display_name)
            field = SimpleNamespace(field_name=stored_name, field_type='MEDIUM')
            self.assertEqual(_field_export_display_label(None, field), display_name)

    def test_retired_generated_field_display_name_handles_different_tokens(self):
        stored = '__retired_generated__abc123__retired_generated__xyz789__Medium Field 2'
        self.assertEqual(get_original_generated_field_name(stored), 'Medium Field 2')

    def test_normal_field_name_is_not_modified(self):
        names = [
            'Johnsburg - Hiller - Small - NE',
            'Practice __retired_generated__abc123__ Field',
            '__retired_generated__not wrapped',
        ]
        for name in names:
            self.assertEqual(get_field_display_name(name), name)
            self.assertFalse(is_retired_generated_field(name))

    def test_field_retirement_is_idempotent_and_keeps_reference_identity(self):
        field_id = uuid.uuid4()
        field = SimpleNamespace(id=field_id, field_name='Medium Field 1', is_active=True)
        historical_game = SimpleNamespace(field_instance_id=field_id, field_instance=field)

        self.assertTrue(retire_generated_field(field))
        once = field.field_name
        self.assertFalse(retire_generated_field(field))

        self.assertEqual(field.field_name, once)
        self.assertEqual(field.field_name.count('__retired_generated__'), 1)
        self.assertFalse(field.is_active)
        self.assertEqual(historical_game.field_instance_id, field_id)
        self.assertIs(historical_game.field_instance, field)
        self.assertEqual(get_field_display_name(historical_game.field_instance), 'Medium Field 1')

    def test_already_corrupted_field_is_not_wrapped_again(self):
        stored = '__retired_generated__abc123__retired_generated__xyz789__Medium Field 2'
        field = SimpleNamespace(id=uuid.uuid4(), field_name=stored, is_active=True)
        self.assertFalse(retire_generated_field(field))
        self.assertEqual(field.field_name, stored)
        self.assertFalse(field.is_active)

    def test_public_display_never_returns_internal_markers(self):
        self.assertEqual(
            get_public_field_display_name(
                '__retired_generated__f9ac615f__retired_generated__f9ac615f__Medium Field 1'
            ),
            'Medium Field 1',
        )
        for malformed in ('__generated__f9ac615f', '_retired_Field 1',
                          '__retired_generated__broken'):
            self.assertIsNone(get_public_field_display_name(malformed))


if __name__ == '__main__':
    unittest.main()
