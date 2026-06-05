import unittest
from datetime import date, time
from types import SimpleNamespace

from app.routes.api import (
    _format_schedule_export_date,
    _format_schedule_export_status,
    _format_schedule_export_time,
    _schedule_export_row_values,
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
                'Wave 1 TWO_SMALL_ONE_MEDIUM Small Field 2',
                'SMALL',
                'SCHEDULED',
            ],
        )

    def test_turf_export_label_uses_wave_metadata_not_stale_field_name(self):
        wave = SimpleNamespace(sequence_number=1, preferred_layout_code='TWO_SMALL_ONE_MEDIUM')
        slot = SimpleNamespace(field_type='SMALL', turf_wave_id='wave-id', turf_wave=wave)
        field = SimpleNamespace(field_name='Wave 2 TWO_SMALL_ONE_MEDIUM Small Field 1')

        self.assertEqual(
            _turf_field_export_label(slot, field),
            'Wave 1 TWO_SMALL_ONE_MEDIUM Small Field 1',
        )


if __name__ == '__main__':
    unittest.main()
