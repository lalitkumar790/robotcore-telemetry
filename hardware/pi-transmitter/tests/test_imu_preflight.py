import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, HERE)

from imu_preflight import wait_for_fresh_imu


class FakeIMU:
    def __init__(self, results):
        self.results = list(results)
        self.last = self.results[-1]

    def get_reading(self):
        if self.results:
            self.last = self.results.pop(0)
        return self.last


class IMUPreflightTests(unittest.TestCase):
    def test_passes_when_first_reading_is_fresh(self):
        reading = object()
        imu = FakeIMU([(reading, True, 0.05, None)])

        self.assertTrue(wait_for_fresh_imu(imu, timeout_s=1.0))

    def test_waits_until_a_fresh_reading_arrives(self):
        reading = object()
        imu = FakeIMU([
            (None, False, None, None),
            (None, False, None, "TimeoutError"),
            (reading, True, 0.08, None),
        ])

        self.assertTrue(
            wait_for_fresh_imu(imu, timeout_s=1.0, poll_interval_s=0.0)
        )

    def test_times_out_when_no_fresh_reading_arrives(self):
        imu = FakeIMU([(None, False, None, "TimeoutError")])

        self.assertFalse(
            wait_for_fresh_imu(
                imu, timeout_s=0.01, poll_interval_s=0.001, report_interval_s=1.0
            )
        )


if __name__ == "__main__":
    unittest.main()
