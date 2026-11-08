import copy
import unittest
from pathlib import Path

from crm_retention_lab.config import load_config, parse_ts, validate_config

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "configs/smoke_v0_1.json")

    def test_profile_keeps_engineering_data_out_of_final_period(self):
        self.assertEqual(self.config["population"]["first_delivery_customers"], 1000)
        self.assertLessEqual(parse_ts(self.config["population"]["observation_end_exclusive"]),
                             parse_ts(self.config["splits"]["final_test"]["start_inclusive"]))
        self.assertIn("not_final_evaluation", self.config["runtime"]["purpose"])

    def test_unimplemented_scenario_and_zero_population_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Supported stage-1"):
            load_config(ROOT / "configs/smoke_v0_1.json", scenario="response_shift")
        with self.assertRaisesRegex(ValueError, "positive integer"):
            load_config(ROOT / "configs/smoke_v0_1.json", customers=0)

    def test_settlement_and_operational_availability_assumptions_are_enforced(self):
        for key, value in (("operational_reporting_lag_days", 1),
                           ("max_order_adjustment_recording_days_after_payment", 31)):
            config = copy.deepcopy(self.config)
            config["population"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(config)
        config = copy.deepcopy(self.config)
        config["generator"]["refund"]["days_after_payment_max"] = 31
        with self.assertRaisesRegex(ValueError, "settlement bound"):
            validate_config(config)

    def test_invalid_randomization_is_rejected(self):
        config = copy.deepcopy(self.config)
        config["experiment"]["arms"][0]["probability"] = 0.8
        with self.assertRaisesRegex(ValueError, "sum to one"):
            validate_config(config)

    def test_timezone_must_be_explicit_and_match_the_daily_slot(self):
        with self.assertRaisesRegex(ValueError, "Timezone required"):
            parse_ts("2025-01-01T00:00:00")
        config = copy.deepcopy(self.config)
        config["population"]["first_delivery_start_inclusive"] = "2025-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "Asia/Seoul"):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
