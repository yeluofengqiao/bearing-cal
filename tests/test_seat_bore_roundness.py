from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from seat_bore_roundness import (
    RoundnessPoint,
    SeatBoreRoundnessInputs,
    calculate_seat_bore_roundness,
    parse_roundness_points,
)


def sinusoidal_roundness_points() -> tuple[RoundnessPoint, ...]:
    return tuple(
        RoundnessPoint(
            angle_deg=float(angle),
            deviation_mm=-0.045 * math.cos(math.radians(angle)),
        )
        for angle in range(0, 360, 45)
    )


def local_low_roundness_points() -> tuple[RoundnessPoint, ...]:
    deviations = {
        0: -0.045,
        45: -0.025,
        90: 0.0,
        135: 0.010,
        180: 0.030,
        225: 0.010,
        270: 0.0,
        315: -0.020,
    }
    return tuple(
        RoundnessPoint(angle_deg=float(angle), deviation_mm=deviation)
        for angle, deviation in deviations.items()
    )


class SeatBoreRoundnessModelTests(unittest.TestCase):
    def test_zero_roundness_matches_baseline(self) -> None:
        points = tuple(
            RoundnessPoint(angle_deg=float(angle), deviation_mm=0.0)
            for angle in range(0, 360, 45)
        )
        result = calculate_seat_bore_roundness(
            SeatBoreRoundnessInputs(
                roundness_points=points,
                transfer_coefficients=(0.5,),
            )
        )

        scenario = result.scenarios[0]
        self.assertAlmostEqual(1.0, scenario.peak_ball_load_ratio, places=6)
        self.assertAlmostEqual(1.0, scenario.damage_ratio, places=6)
        self.assertAlmostEqual(1.0, scenario.relative_life_ratio, places=6)

    def test_life_reduces_as_transfer_coefficient_increases(self) -> None:
        result = calculate_seat_bore_roundness(
            SeatBoreRoundnessInputs(
                roundness_points=sinusoidal_roundness_points(),
                transfer_coefficients=(0.25, 0.5, 1.0),
            )
        )

        damage_ratios = [scenario.damage_ratio for scenario in result.scenarios]
        life_ratios = [scenario.relative_life_ratio for scenario in result.scenarios]
        self.assertLess(damage_ratios[0], damage_ratios[1])
        self.assertLess(damage_ratios[1], damage_ratios[2])
        self.assertGreater(life_ratios[0], life_ratios[1])
        self.assertGreater(life_ratios[1], life_ratios[2])

    def test_profile_phase_changes_damage_when_defect_moves_out_of_load_zone(self) -> None:
        load_zone_result = calculate_seat_bore_roundness(
            SeatBoreRoundnessInputs(
                roundness_points=local_low_roundness_points(),
                transfer_coefficients=(0.5,),
                profile_phase_deg=0.0,
            )
        )
        opposite_zone_result = calculate_seat_bore_roundness(
            SeatBoreRoundnessInputs(
                roundness_points=local_low_roundness_points(),
                transfer_coefficients=(0.5,),
                profile_phase_deg=180.0,
            )
        )

        self.assertGreater(
            load_zone_result.scenarios[0].damage_ratio,
            opposite_zone_result.scenarios[0].damage_ratio,
        )

    def test_parse_roundness_points_accepts_comma_and_space_formats(self) -> None:
        points = parse_roundness_points("0, -0.045\n90 0.000\n180, 0.045\n270 0.000")

        self.assertEqual(4, len(points))
        self.assertAlmostEqual(-0.045, points[0].deviation_mm)


if __name__ == "__main__":
    unittest.main()
