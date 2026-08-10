import unittest
from datetime import date, time

from app.services.facility_layout_validation import validate_timeslot_demands


class TimeslotCapacityValidationTest(unittest.TestCase):
    day = date(2026, 8, 16)
    host = 'Johnsburg Stadium'

    def validate(self, waves, layouts):
        demands = {(self.day, self.host, kickoff): demand for kickoff, demand in waves.items()}
        capacities = {
            (self.day, self.host, kickoff): allowed
            for kickoff, allowed in layouts.items()
        }
        return validate_timeslot_demands(demands, capacities)

    def test_five_sequential_large_games_reuse_one_field(self):
        kickoffs = [time(hour, 0) for hour in (9, 10, 11, 12, 13)]
        result = self.validate(
            {kickoff: {'LARGE': 1} for kickoff in kickoffs},
            {kickoff: [{'LARGE': 1}] for kickoff in kickoffs},
        )
        self.assertTrue(result['valid'])
        self.assertEqual(result['peak_by_size']['LARGE'], 1)

    def test_two_concurrent_large_games_report_shortage_of_one(self):
        result = self.validate(
            {time(9): {'LARGE': 2}},
            {time(9): [{'LARGE': 1}]},
        )
        self.assertFalse(result['valid'])
        self.assertEqual(result['shortages'][0]['shortage_by_size']['LARGE'], 1)
        self.assertFalse(result['shortages'][0]['unsupported_combination'])

    def test_large_and_small_allowed_configuration(self):
        result = self.validate(
            {time(9): {'LARGE': 1, 'SMALL': 1}},
            {time(9): [{'LARGE': 1, 'SMALL': 1}]},
        )
        self.assertTrue(result['valid'])

    def test_individually_supported_but_disallowed_combination(self):
        result = self.validate(
            {time(9): {'LARGE': 1, 'MEDIUM': 1}},
            {time(9): [{'LARGE': 1}, {'MEDIUM': 1}]},
        )
        self.assertFalse(result['valid'])
        self.assertTrue(result['shortages'][0]['unsupported_combination'])

    def test_adjacent_hour_windows_reuse_field(self):
        result = self.validate(
            {time(9): {'LARGE': 1}, time(10): {'LARGE': 1}},
            {time(9): [{'LARGE': 1}], time(10): [{'LARGE': 1}]},
        )
        self.assertTrue(result['valid'])


if __name__ == '__main__':
    unittest.main()
