from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, build_lubrication_recommendation, resolve_ball_load_components


class BearingWebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_home_page_still_renders_existing_calculator(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("通用轴承机电联合仿真计算器".encode("utf-8"), response.data)
        self.assertIn("圆锥预压垫片".encode("utf-8"), response.data)

    def test_tapered_preload_page_renders(self) -> None:
        response = self.client.get("/tapered-preload")

        self.assertEqual(response.status_code, 200)
        self.assertIn("圆锥滚子轴承预压垫片推荐计算器".encode("utf-8"), response.data)
        self.assertIn("生成推荐垫片点".encode("utf-8"), response.data)

    def test_ball_stiffness_page_renders(self) -> None:
        response = self.client.get("/ball-stiffness")

        self.assertEqual(response.status_code, 200)
        self.assertIn("B40 球轴承刚度矩阵计算器".encode("utf-8"), response.data)
        self.assertIn("计算刚度矩阵".encode("utf-8"), response.data)
        self.assertIn("径向合力 Fr".encode("utf-8"), response.data)
        self.assertNotIn("平移差分步长".encode("utf-8"), response.data)
        self.assertNotIn("转角差分步长".encode("utf-8"), response.data)

    def test_home_post_renders_lubrication_recommendation(self) -> None:
        response = self.client.post("/", data={})

        self.assertEqual(response.status_code, 200)
        self.assertIn("润滑建议".encode("utf-8"), response.data)
        self.assertIn("经验阈值".encode("utf-8"), response.data)

    def test_lubrication_recommendation_flags_low_kappa_and_lambda(self) -> None:
        recommendation = build_lubrication_recommendation(
            kappa=0.72,
            minimum_inner_lambda=0.84,
            minimum_outer_lambda=1.15,
        )

        self.assertEqual("danger", recommendation["level"])
        self.assertIn("边界润滑风险", recommendation["summary"])
        self.assertTrue(
            any("提高运行黏度" in action for action in recommendation["actions"])
        )

    def test_lubrication_recommendation_adds_reverse_signal_alert(self) -> None:
        recommendation = build_lubrication_recommendation(
            kappa=4.60,
            minimum_inner_lambda=0.82,
            minimum_outer_lambda=1.35,
        )

        self.assertTrue(recommendation["alerts"])
        self.assertEqual("danger", recommendation["alerts"][0]["level"])
        self.assertIn("λ 偏低但 κ 偏高", recommendation["alerts"][0]["title"])
        self.assertTrue(
            any("不要只看 κ 下结论" in action for action in recommendation["alerts"][0]["actions"])
        )

    def test_tapered_preload_post_returns_recommendation(self) -> None:
        response = self.client.post(
            "/tapered-preload",
            data={
                "zero_endplay_shim_mm": "2.5",
                "minimum_hot_preload_n": "200",
                "target_hot_preload_n": "1000",
                "shim_step_mm": "0.02",
                "preload_direction": "thinner_increases_preload",
                "left_bearing_stiffness_n_per_mm": "100000",
                "right_bearing_stiffness_n_per_mm": "100000",
                "housing_stiffness_n_per_mm": "200000",
                "shaft_stiffness_n_per_mm": "200000",
                "housing_alpha_per_c": "0.000023",
                "housing_effective_span_mm": "60",
                "housing_delta_temp_c": "80",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("离散推荐点".encode("utf-8"), response.data)
        self.assertIn("2.360 mm".encode("utf-8"), response.data)
        self.assertIn("垫片点比较".encode("utf-8"), response.data)

    def test_ball_stiffness_post_returns_matrix(self) -> None:
        response = self.client.post("/ball-stiffness", data={})

        self.assertEqual(response.status_code, 200)
        self.assertIn("5×5 刚度矩阵".encode("utf-8"), response.data)
        self.assertIn("参与接触钢球数".encode("utf-8"), response.data)
        self.assertIn("Fx (N)".encode("utf-8"), response.data)
        self.assertIn("实际 Fx / Fy".encode("utf-8"), response.data)

    def test_ball_stiffness_resolves_fr_fa_to_cartesian_components(self) -> None:
        components = resolve_ball_load_components(
            {
                "load_input_mode": "polar",
                "radial_force_n": 1000.0,
                "radial_force_angle_deg": 30.0,
                "axial_force_n": 500.0,
            }
        )

        self.assertAlmostEqual(866.0254, components["fx_n"], places=3)
        self.assertAlmostEqual(500.0, components["fy_n"], places=3)
        self.assertAlmostEqual(500.0, components["fz_n"], places=3)


if __name__ == "__main__":
    unittest.main()
