#!/Applications/Xcode.app/Contents/Developer/usr/bin/python3

import unittest
from datetime import datetime, timedelta

from analyze_lab_status import (
    METRIC_SPECS,
    MetricEvaluation,
    build_conclusion,
    calculate_out_of_range_duration,
    format_duration,
    is_out_of_range,
)


class DurationRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 7, 12, 0, 0)
        self.end = self.start + timedelta(hours=4)

    def points(self, values: list[tuple[int, float]]):
        return tuple(
            (self.start + timedelta(minutes=minute), value)
            for minute, value in values
        )

    def test_range_boundaries_are_normal(self) -> None:
        self.assertFalse(is_out_of_range(20.0, (20.0, 25.0)))
        self.assertFalse(is_out_of_range(25.0, (20.0, 25.0)))
        self.assertFalse(is_out_of_range(35.0, (35.0, 60.0)))
        self.assertFalse(is_out_of_range(60.0, (35.0, 60.0)))

    def test_exactly_two_hours_is_normal(self) -> None:
        points = self.points(
            [(0, 26.0), (30, 26.0), (60, 26.0), (90, 26.0), (120, 22.0)]
        )
        duration = calculate_out_of_range_duration(points, (20.0, 25.0), self.end)
        evaluation = MetricEvaluation("内间", METRIC_SPECS[0], points, duration)
        self.assertEqual(duration, timedelta(hours=2))
        self.assertFalse(evaluation.is_abnormal)
        self.assertTrue(
            build_conclusion([evaluation], self.start, self.end).startswith(
                "实验室温湿度监测：正常。"
            )
        )

    def test_more_than_two_hours_is_abnormal(self) -> None:
        points = self.points(
            [
                (0, 26.0),
                (30, 26.0),
                (60, 26.0),
                (90, 26.0),
                (120, 26.0),
                (150, 22.0),
            ]
        )
        duration = calculate_out_of_range_duration(points, (20.0, 25.0), self.end)
        evaluation = MetricEvaluation("内间", METRIC_SPECS[0], points, duration)
        self.assertEqual(duration, timedelta(hours=2, minutes=30))
        self.assertTrue(evaluation.is_abnormal)
        self.assertTrue(
            build_conclusion([evaluation], self.start, self.end).startswith(
                "实验室温湿度监测：不正常。"
            )
        )

    def test_long_data_gap_is_capped_at_thirty_minutes(self) -> None:
        points = self.points([(0, 26.0), (180, 22.0)])
        duration = calculate_out_of_range_duration(points, (20.0, 25.0), self.end)
        self.assertEqual(duration, timedelta(minutes=30))

    def test_abnormal_seconds_are_not_rounded_down_to_two_hours(self) -> None:
        self.assertEqual(
            format_duration(timedelta(hours=2, seconds=1)), "2 小时 1 分钟"
        )


if __name__ == "__main__":
    unittest.main()
