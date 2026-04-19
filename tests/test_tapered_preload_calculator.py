from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tapered_preload_calculator import TaperedPreloadInputs, calculate_tapered_preload, evaluate_shim


class TaperedPreloadCalculatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = TaperedPreloadInputs(
            zero_endplay_shim_mm=2.5,
            minimum_hot_preload_n=200.0,
            target_hot_preload_n=1000.0,
            left_bearing_stiffness_n_per_mm=100000.0,
            right_bearing_stiffness_n_per_mm=100000.0,
            housing_stiffness_n_per_mm=200000.0,
            shaft_stiffness_n_per_mm=200000.0,
            housing_alpha_per_c=23e-6,
            housing_effective_span_mm=60.0,
            housing_delta_temp_c=80.0,
            shim_step_mm=0.02,
        )

    def test_nominal_recommendation_matches_series_stiffness_model(self) -> None:
        result = calculate_tapered_preload(self.inputs)

        self.assertAlmostEqual(result.equivalent_stiffness_n_per_mm, 33333.333333, places=3)
        self.assertAlmostEqual(result.housing_thermal_growth_mm, 0.1104, places=6)
        self.assertAlmostEqual(result.nominal_shim_mm, 2.3596, places=4)
        self.assertAlmostEqual(result.selected_shim_mm, 2.36, places=6)
        self.assertAlmostEqual(result.selected_point.cold_preload_n, 4666.666667, places=3)
        self.assertAlmostEqual(result.selected_point.hot_preload_n, 986.666667, places=3)

    def test_thicker_point_can_result_in_hot_clearance(self) -> None:
        point = evaluate_shim(self.inputs, 2.40, nominal_shim_mm=2.3596)

        self.assertAlmostEqual(point.cold_preload_n, 3333.333333, places=3)
        self.assertAlmostEqual(point.hot_clearance_mm, 0.0104, places=6)
        self.assertEqual(point.hot_preload_n, 0.0)
        self.assertFalse(point.meets_min_hot_preload)

    def test_reverse_direction_moves_recommended_shim_to_larger_value(self) -> None:
        reverse_inputs = TaperedPreloadInputs(
            **{
                **self.inputs.__dict__,
                "preload_direction": "thicker_increases_preload",
            }
        )

        result = calculate_tapered_preload(reverse_inputs)

        self.assertAlmostEqual(result.nominal_shim_mm, 2.6404, places=4)
        self.assertGreater(result.selected_shim_mm, reverse_inputs.zero_endplay_shim_mm)


if __name__ == "__main__":
    unittest.main()
