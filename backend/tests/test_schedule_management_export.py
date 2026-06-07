import unittest
from datetime import date, time
from types import SimpleNamespace

from app.routes.api import (
    _format_schedule_export_date,
    _format_schedule_export_status,
    _format_schedule_export_time,
    _schedule_export_row_values,
    _field_export_display_issue,
    _turf_field_export_label,
)


class ScheduleManagementExportTest(unittest.TestCase):
    def test_export_formats_match_spreadsheet_columns(self):
        self.assertEqual(_format_schedule_export_date(date(2026, 8, 9)), '8/9/2026')
        self.assertEqual(_format_schedule_export_time(time(9, 0)), '9:00')
        self.assertEqual(_format_schedule_export_time(time(13, 5)), '13:05')
        self.assertEqual(_format_schedule_export_status('scheduled'), 'SCHEDULED')

    def test_export_row_uses_compact_schedule_shape(self):
        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
            SimpleNamespace(field_type='small'),
            SimpleNamespace(field_name='Wave 1 TWO_SMALL_ONE_MEDIUM Small Field 2'),
            SimpleNamespace(name='Westosha Stadium'),
            SimpleNamespace(name='Westosha Coed 2-3 Maroon'),
            SimpleNamespace(name='LCS Coed 2-3 Red'),
            SimpleNamespace(division_group='Coed', name='2-3'),
            SimpleNamespace(code='scheduled'),
        )

        self.assertEqual(
            values,
            [
                '8/9/2026',
                '9:00',
                'coed_2_3',
                'Westosha Coed 2-3 Maroon',
                'LCS Coed 2-3 Red',
                'Westosha Stadium',
                'Small Field 2',
                'SMALL',
                'SCHEDULED',
            ],
        )

    def test_turf_export_label_strips_wave_metadata_from_stored_field_name(self):
        wave = SimpleNamespace(sequence_number=1, preferred_layout_code='TWO_SMALL_ONE_MEDIUM')
        slot = SimpleNamespace(field_type='SMALL', turf_wave_id='wave-id', turf_wave=wave)
        field = SimpleNamespace(field_name='Wave 2 TWO_SMALL_ONE_MEDIUM Small Field 1')

        self.assertEqual(_turf_field_export_label(slot, field), 'Small Field 1')

    def test_turf_export_label_preserves_non_sequential_explicit_slot(self):
        slot = SimpleNamespace(field_type='MEDIUM', turf_wave_id='wave-id', turf_wave=SimpleNamespace(slots=[]))
        field = SimpleNamespace(field_name='Wave 5 TWO_MEDIUM Medium Field 2')

        self.assertEqual(_turf_field_export_label(slot, field), 'Medium Field 2')

    def test_export_field_values_do_not_include_wave_or_layout_codes(self):
        cases = [
            ('Wave 1 Small Field 1', 'Small Field 1'),
            ('Wave 2 Large Field 1', 'Large Field 1'),
            ('Wave 5 Medium Field 2', 'Medium Field 2'),
            ('THREE_SMALL Small Field 1', 'Small Field 1'),
            ('TWO_MEDIUM Medium Field 2', 'Medium Field 2'),
            ('ONE_SMALL_ONE_LARGE Large Field 1', 'Large Field 1'),
        ]
        for stored, expected in cases:
            values = _schedule_export_row_values(
                SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
                SimpleNamespace(field_type='MEDIUM' if 'Medium' in stored else ('LARGE' if 'Large' in stored else 'SMALL')),
                SimpleNamespace(field_name=stored),
                SimpleNamespace(name='Westosha Stadium'),
                SimpleNamespace(name='Home'),
                SimpleNamespace(name='Away'),
                SimpleNamespace(division_group='Coed', name='2-3'),
                SimpleNamespace(code='scheduled'),
            )
            self.assertEqual(values[6], expected)
            self.assertNotIn('Wave', values[6])
            self.assertNotRegex(values[6], r'THREE_SMALL|TWO_MEDIUM|ONE_SMALL_ONE_LARGE')

    def test_export_display_issue_detects_visible_internal_terms(self):
        self.assertEqual(_field_export_display_issue('Wave 1 Small Field 1'), 'Export display issue: Field column contains Wave terminology.')
        self.assertEqual(_field_export_display_issue('TWO_MEDIUM Medium Field 2'), 'Export display issue: Field column should show explicit field slot only.')


class ScheduleManagementExportIntegrityGuardTest(unittest.TestCase):
    def test_export_row_downgrades_scheduled_without_complete_assignment(self):
        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(9, 0)),
            None,
            None,
            SimpleNamespace(name='Westosha Stadium'),
            SimpleNamespace(name='Home'),
            SimpleNamespace(name='Away'),
            SimpleNamespace(division_group='Coed', name='2-3'),
            SimpleNamespace(code='SCHEDULED'),
        )

        self.assertEqual(values[-1], 'VALIDATION_FAILED')
        self.assertEqual(values[6], '')
        self.assertEqual(values[7], '')

if __name__ == '__main__':
    unittest.main()
