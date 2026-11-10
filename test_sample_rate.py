import unittest

from client_app.sample_rate import RollingSampleRate


class RollingSampleRateTest(unittest.TestCase):
    def test_reports_samples_per_second_over_recent_window(self):
        rate = RollingSampleRate(window_seconds=1.0)

        for timestamp in (10.0, 10.25, 10.5, 10.75, 11.0):
            rate.record(timestamp)

        self.assertEqual(rate.hz, 4.0)

    def test_discards_samples_older_than_the_window(self):
        rate = RollingSampleRate(window_seconds=1.0)

        for timestamp in (10.0, 10.5, 11.0, 11.5):
            rate.record(timestamp)

        self.assertEqual(rate.hz, 2.0)

    def test_reset_returns_to_an_unavailable_rate(self):
        rate = RollingSampleRate(window_seconds=1.0)
        rate.record(10.0)
        rate.record(10.5)

        rate.reset()

        self.assertIsNone(rate.hz)

    def test_rejects_a_non_positive_window(self):
        with self.assertRaises(ValueError):
            RollingSampleRate(window_seconds=0)


if __name__ == "__main__":
    unittest.main()
