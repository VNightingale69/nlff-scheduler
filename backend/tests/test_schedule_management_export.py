import unittest
from datetime import date, time
from types import SimpleNamespace

from app.routes.api import (
    _format_schedule_export_date,
    _format_schedule_export_status,
    _format_schedule_export_time,
    _schedule_export_row_values,
)


class ScheduleManagementExportTest(unittest.TestCase):
    def test_export_formats_match_spreadsheet_columns(self):
        self.assertEqual(_format_schedule_export_date(date(2026, 8, 9)), '8/9/2026')
        self.assertEqual(_format_schedule_export_time(time(9, 0)), '9:00')
        self.assertEqual(_format_schedule_export_time(time(13, 5)), '13:05')
        self.assertEqual(_format_schedule_export_status('scheduled'), 'SCHEDULED')

    def test_export_row_uses_authoritative_turf_wave_metadata_for_field_label(self):
        field = SimpleNamespace(id='field-1', field_name='Wave 4 ONE_SMALL_ONE_LARGE Small Field 2', field_type='small')
        wave = SimpleNamespace(sequence_number=2, preferred_layout_code='TWO_SMALL_ONE_MEDIUM', slots=[])
        slot = SimpleNamespace(
            id='slot-1',
            field_type='small',
            field_instance=field,
            field_instance_id=field.id,
            turf_wave_id='wave-1',
            turf_wave=wave,
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        wave.slots = [slot]

        values = _schedule_export_row_values(
            SimpleNamespace(game_date=date(2026, 8, 9), kickoff_time=time(10, 0)),
            slot,
            field,
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
                '10:00',
                'coed_2_3',
                'Westosha Coed 2-3 Maroon',
                'LCS Coed 2-3 Red',
                'Westosha Stadium',
                'Wave 2 TWO_SMALL_ONE_MEDIUM Small Field 1',
                'SMALL',
                'SCHEDULED',
            ],
        )


if __name__ == '__main__':
    unittest.main()
