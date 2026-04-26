from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ball_bearing_stiffness import BallBearingStiffnessInputs


class BallBearingStiffnessModelTests(unittest.TestCase):
    def test_effective_modulus_uses_two_body_reduced_modulus(self) -> None:
        inputs = BallBearingStiffnessInputs(elastic_modulus_mpa=206000.0, poisson_ratio=0.3)

        self.assertAlmostEqual(
            206000.0 / (2.0 * (1.0 - 0.3**2)),
            inputs.effective_modulus_mpa,
        )


if __name__ == "__main__":
    unittest.main()
