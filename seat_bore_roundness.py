from __future__ import annotations

import math
from numbers import Integral
import re
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import least_squares

from ball_bearing_stiffness import BallBearingStiffnessInputs, BallBearingStiffnessModel


DEFAULT_IMAGE_ROUNDNESS_POINTS = (
    (0.0, -0.0527),
    (22.5, -0.0444),
    (45.0, -0.0131),
    (67.5, 0.0238),
    (90.0, 0.0161),
    (112.5, 0.0035),
    (135.0, -0.0185),
    (157.5, -0.0231),
    (180.0, 0.0024),
    (202.5, 0.0260),
    (225.0, 0.0348),
    (247.5, 0.0257),
    (270.0, -0.0314),
    (292.5, -0.0493),
    (315.0, -0.0149),
    (337.5, 0.0234),
)


REQUIRED_CUSTOMER_DATA = (
    "座孔圆度原始点列或 CMM 导出文件，而不只是截图或单一圆度值。",
    "圆度测量基准、截面位置、压装前/热套后/冷却后的状态说明。",
    "轴承外圈装入后的外径圆度或沟道圆度复测数据。",
    "输入轴径向/轴向载荷谱、转速、温度和耐久循环比例。",
    "轴承实测游隙、壳体孔实际尺寸、外圈实际尺寸和装配配合状态。",
)


CUSTOMER_REPLY_POINTS = (
    "现有圆度图显示座孔形状异常会改变轴承装配后的外圈形状，不能仅凭外圈松配合判断为无影响。",
    "若座孔异常方向落在轴承承载区，局部游隙会被进一步消耗，钢球载荷分配会向少数钢球集中。",
    "寿命影响需要基于圆度点列、外圈变形传递比例和实际载荷谱计算；当前只能先给相对寿命风险评估。",
    "建议优先复核壳体加工和热套工艺，并对装入后的外圈/沟道圆度进行复测确认。",
)


@dataclass(frozen=True)
class RoundnessPoint:
    angle_deg: float
    deviation_mm: float

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RoundnessBallDetail:
    index: int
    angle_deg: float
    roundness_deviation_um: float
    effective_inward_um: float
    local_clearance_um: float
    normal_approach_um: float
    normal_load_n: float
    contact_angle_deg: float
    damage_share_pct: float
    stress_index: float

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RoundnessScenarioResult:
    transfer_coefficient: float
    deformation_peak_to_valley_um: float
    displacement_x_um: float
    displacement_y_um: float
    displacement_z_um: float
    residual_force_n: float
    solver_converged: bool
    active_ball_count: int
    peak_ball_load_n: float
    peak_ball_load_ratio: float
    damage_index: float
    damage_ratio: float
    relative_life_ratio: float
    contact_stress_index: float
    min_local_clearance_um: float
    worst_angle_deg: float
    details: list[RoundnessBallDetail]

    def to_dict(self):
        payload = asdict(self)
        payload["details"] = [detail.to_dict() for detail in self.details]
        return payload


@dataclass(frozen=True)
class SeatBoreRoundnessInputs:
    ball_count: int = 8
    ball_diameter_mm: float = 15.081
    pitch_diameter_mm: float = 73.0
    inner_groove_radius_mm: float = 15.081 * 0.52
    outer_groove_radius_mm: float = 15.081 * 0.53
    diametral_clearance_mm: float = 0.015
    elastic_modulus_mpa: float = 206000.0
    poisson_ratio: float = 0.3
    radial_load_n: float = 2000.0
    radial_load_angle_deg: float = 0.0
    axial_load_n: float = 0.0
    profile_phase_deg: float = 0.0
    fatigue_exponent: float = 3.0
    transfer_coefficients: tuple[float, ...] = (0.25, 0.5, 1.0)
    roundness_points: tuple[RoundnessPoint, ...] = tuple(
        RoundnessPoint(angle, deviation) for angle, deviation in DEFAULT_IMAGE_ROUNDNESS_POINTS
    )

    @property
    def groove_span_mm(self) -> float:
        return (
            self.inner_groove_radius_mm
            + self.outer_groove_radius_mm
            - self.ball_diameter_mm
        )

    @property
    def pitch_radius_mm(self) -> float:
        return 0.5 * self.pitch_diameter_mm

    def target_vector(self) -> np.ndarray:
        angle_rad = math.radians(self.radial_load_angle_deg)
        return np.array(
            [
                self.radial_load_n * math.cos(angle_rad),
                self.radial_load_n * math.sin(angle_rad),
                self.axial_load_n,
            ],
            dtype=float,
        )

    def validate(self) -> None:
        scalar_values = {
            "pitch_diameter_mm": self.pitch_diameter_mm,
            "diametral_clearance_mm": self.diametral_clearance_mm,
            "poisson_ratio": self.poisson_ratio,
            "radial_load_n": self.radial_load_n,
            "radial_load_angle_deg": self.radial_load_angle_deg,
            "axial_load_n": self.axial_load_n,
            "profile_phase_deg": self.profile_phase_deg,
        }
        if any(not math.isfinite(float(value)) for value in scalar_values.values()):
            raise ValueError("座孔圆度计算输入必须是有限数字。")
        positive_fields = {
            "ball_diameter_mm": self.ball_diameter_mm,
            "pitch_diameter_mm": self.pitch_diameter_mm,
            "inner_groove_radius_mm": self.inner_groove_radius_mm,
            "outer_groove_radius_mm": self.outer_groove_radius_mm,
            "elastic_modulus_mpa": self.elastic_modulus_mpa,
            "fatigue_exponent": self.fatigue_exponent,
        }
        if any(not math.isfinite(float(value)) for value in positive_fields.values()):
            raise ValueError("座孔圆度几何和材料输入必须是有限数字。")
        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} 必须大于 0。")

        if isinstance(self.ball_count, bool) or not isinstance(self.ball_count, Integral):
            raise ValueError("钢球数必须是整数。")
        if self.ball_count < 3:
            raise ValueError("钢球数至少需要 3。")
        if self.pitch_diameter_mm <= self.ball_diameter_mm:
            raise ValueError("节圆直径必须大于钢球直径。")
        if self.diametral_clearance_mm < 0:
            raise ValueError("直径游隙不能为负数。")
        if self.radial_load_n < 0:
            raise ValueError("径向载荷不能为负数；反向载荷请调整径向力方向角。")
        if not 0.0 < self.poisson_ratio < 0.5:
            raise ValueError("泊松比需要在 0 和 0.5 之间。")
        if self.groove_span_mm <= 0:
            raise ValueError("内外圈沟曲率半径之和必须大于钢球直径。")
        if len(self.roundness_points) < 3:
            raise ValueError("圆度点列至少需要 3 个角度点。")
        for point in self.roundness_points:
            if not math.isfinite(point.angle_deg) or not math.isfinite(point.deviation_mm):
                raise ValueError("圆度点列包含无效数字。")
        for coefficient in self.transfer_coefficients:
            if not math.isfinite(coefficient):
                raise ValueError("外圈变形传递系数必须是有限数字。")
            if coefficient < 0:
                raise ValueError("外圈变形传递系数不能为负数。")


@dataclass(frozen=True)
class SeatBoreRoundnessResult:
    baseline: RoundnessScenarioResult
    scenarios: list[RoundnessScenarioResult]
    roundness_peak_to_valley_um: float
    centered_roundness_points: list[RoundnessPoint]
    customer_reply_points: tuple[str, ...] = CUSTOMER_REPLY_POINTS
    required_customer_data: tuple[str, ...] = REQUIRED_CUSTOMER_DATA

    def to_dict(self):
        return {
            "baseline": self.baseline.to_dict(),
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "roundness_peak_to_valley_um": self.roundness_peak_to_valley_um,
            "centered_roundness_points": [
                point.to_dict() for point in self.centered_roundness_points
            ],
            "customer_reply_points": list(self.customer_reply_points),
            "required_customer_data": list(self.required_customer_data),
        }


def parse_roundness_points(raw_text: str) -> tuple[RoundnessPoint, ...]:
    points: list[RoundnessPoint] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part for part in re.split(r"[,;\s]+", line) if part]
        if len(parts) != 2:
            raise ValueError("圆度点列每行需要两个数字：角度 和 径向偏差(mm)。")
        try:
            angle_deg = float(parts[0])
            deviation_mm = float(parts[1])
        except ValueError as exc:
            raise ValueError("圆度点列包含无法解析的数字。") from exc
        points.append(RoundnessPoint(angle_deg=angle_deg, deviation_mm=deviation_mm))

    if len(points) < 3:
        raise ValueError("圆度点列至少需要 3 个角度点。")
    return tuple(points)


def format_roundness_points(points: Iterable[RoundnessPoint]) -> str:
    return "\n".join(
        f"{point.angle_deg:g}, {point.deviation_mm:.4f}" for point in points
    )


def parse_transfer_coefficients(raw_text: str) -> tuple[float, ...]:
    parts = [part for part in re.split(r"[,;\s]+", raw_text.strip()) if part]
    if not parts:
        raise ValueError("外圈变形传递系数不能为空。")
    try:
        coefficients = tuple(float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("外圈变形传递系数需要输入有效数字。") from exc
    if any(coefficient < 0 for coefficient in coefficients):
        raise ValueError("外圈变形传递系数不能为负数。")
    return coefficients


def format_transfer_coefficients(coefficients: Iterable[float]) -> str:
    return ", ".join(f"{coefficient:g}" for coefficient in coefficients)


class SeatBoreRoundnessModel:
    def __init__(self, inputs: SeatBoreRoundnessInputs):
        self.inputs = inputs
        self.inputs.validate()
        self.angles = np.linspace(0.0, 2.0 * math.pi, inputs.ball_count, endpoint=False)
        self.combined_stiffness = self._combined_contact_stiffness()
        self.centered_points = self._center_roundness_points(inputs.roundness_points)
        self._interp_angles, self._interp_deviations = self._prepare_interpolator(
            self.centered_points
        )
        self.roundness_peak_to_valley_mm = float(
            max(point.deviation_mm for point in self.centered_points)
            - min(point.deviation_mm for point in self.centered_points)
        )

    def _combined_contact_stiffness(self) -> float:
        stiffness_inputs = BallBearingStiffnessInputs(
            ball_count=self.inputs.ball_count,
            ball_diameter_mm=self.inputs.ball_diameter_mm,
            pitch_diameter_mm=self.inputs.pitch_diameter_mm,
            inner_groove_radius_mm=self.inputs.inner_groove_radius_mm,
            outer_groove_radius_mm=self.inputs.outer_groove_radius_mm,
            diametral_clearance_mm=self.inputs.diametral_clearance_mm,
            elastic_modulus_mpa=self.inputs.elastic_modulus_mpa,
            poisson_ratio=self.inputs.poisson_ratio,
        )
        return BallBearingStiffnessModel(stiffness_inputs).combined_stiffness

    @staticmethod
    def _center_roundness_points(points: tuple[RoundnessPoint, ...]) -> list[RoundnessPoint]:
        normalized = sorted(
            (
                RoundnessPoint(angle_deg=point.angle_deg % 360.0, deviation_mm=point.deviation_mm)
                for point in points
            ),
            key=lambda point: point.angle_deg,
        )
        mean_deviation = sum(point.deviation_mm for point in normalized) / len(normalized)
        return [
            RoundnessPoint(
                angle_deg=point.angle_deg,
                deviation_mm=point.deviation_mm - mean_deviation,
            )
            for point in normalized
        ]

    @staticmethod
    def _prepare_interpolator(points: list[RoundnessPoint]) -> tuple[np.ndarray, np.ndarray]:
        collapsed: dict[float, list[float]] = {}
        for point in points:
            collapsed.setdefault(point.angle_deg, []).append(point.deviation_mm)
        angles = np.array(sorted(collapsed), dtype=float)
        deviations = np.array(
            [sum(collapsed[angle]) / len(collapsed[angle]) for angle in angles],
            dtype=float,
        )
        if len(angles) < 3:
            raise ValueError("圆度点列至少需要 3 个不同角度。")
        extended_angles = np.concatenate((angles, [angles[0] + 360.0]))
        extended_deviations = np.concatenate((deviations, [deviations[0]]))
        return extended_angles, extended_deviations

    def roundness_deviation_mm(self, angle_deg: float) -> float:
        angle = angle_deg % 360.0
        if angle < self._interp_angles[0]:
            angle += 360.0
        return float(np.interp(angle, self._interp_angles, self._interp_deviations))

    def effective_inward_mm(self, angle_deg: float, transfer_coefficient: float) -> float:
        source_angle = angle_deg - self.inputs.profile_phase_deg
        # Negative bore-radius deviation means the hole surface intrudes inward.
        return -transfer_coefficient * self.roundness_deviation_mm(source_angle)

    def _contact_state(
        self,
        displacement: np.ndarray,
        transfer_coefficient: float,
        baseline_peak_load: float | None = None,
    ) -> tuple[np.ndarray, list[RoundnessBallDetail], float]:
        dx, dy, dz = np.asarray(displacement, dtype=float)
        base_distance = self.inputs.groove_span_mm
        clearance_allowance = 0.5 * self.inputs.diametral_clearance_mm
        force_vector = np.zeros(3, dtype=float)
        raw_details = []
        damage_index = 0.0

        for index, psi in enumerate(self.angles, start=1):
            angle_deg = math.degrees(psi)
            cos_psi = math.cos(psi)
            sin_psi = math.sin(psi)
            radial_shift = dx * cos_psi + dy * sin_psi
            radial_gap = base_distance + radial_shift
            center_distance = math.hypot(radial_gap, dz)
            effective_inward = self.effective_inward_mm(angle_deg, transfer_coefficient)
            local_clearance = clearance_allowance - effective_inward
            if center_distance <= 1e-12:
                normal_approach = -local_clearance
                contact_angle_deg = 0.0
            else:
                normal_approach = center_distance - base_distance - local_clearance
                contact_angle_deg = math.degrees(math.atan2(dz, radial_gap))

            if normal_approach > 0.0:
                normal_load = self.combined_stiffness * normal_approach**1.5
                radial_force = normal_load * radial_gap / center_distance
                axial_force = normal_load * dz / center_distance
                force_vector[0] += radial_force * cos_psi
                force_vector[1] += radial_force * sin_psi
                force_vector[2] += axial_force
                damage_index += normal_load**self.inputs.fatigue_exponent
            else:
                normal_load = 0.0

            raw_details.append(
                {
                    "index": index,
                    "angle_deg": angle_deg,
                    "roundness_deviation_um": self.roundness_deviation_mm(
                        angle_deg - self.inputs.profile_phase_deg
                    )
                    * 1000.0,
                    "effective_inward_um": effective_inward * 1000.0,
                    "local_clearance_um": local_clearance * 1000.0,
                    "normal_approach_um": max(normal_approach, 0.0) * 1000.0,
                    "normal_load_n": normal_load,
                    "contact_angle_deg": contact_angle_deg if normal_load > 0.0 else 0.0,
                }
            )

        details = []
        for item in raw_details:
            normal_load = item["normal_load_n"]
            damage_share_pct = (
                normal_load**self.inputs.fatigue_exponent / damage_index * 100.0
                if damage_index > 0.0 and normal_load > 0.0
                else 0.0
            )
            stress_index = 0.0
            if baseline_peak_load and baseline_peak_load > 0.0 and normal_load > 0.0:
                stress_index = (normal_load / baseline_peak_load) ** (1.0 / 3.0)
            details.append(
                RoundnessBallDetail(
                    index=item["index"],
                    angle_deg=item["angle_deg"],
                    roundness_deviation_um=item["roundness_deviation_um"],
                    effective_inward_um=item["effective_inward_um"],
                    local_clearance_um=item["local_clearance_um"],
                    normal_approach_um=item["normal_approach_um"],
                    normal_load_n=item["normal_load_n"],
                    contact_angle_deg=item["contact_angle_deg"],
                    damage_share_pct=damage_share_pct,
                    stress_index=stress_index,
                )
            )

        return force_vector, details, damage_index

    def _initial_guesses(self, target: np.ndarray) -> list[np.ndarray]:
        radial_force = math.hypot(target[0], target[1])
        if radial_force > 0.0:
            radial_unit = np.array([target[0] / radial_force, target[1] / radial_force])
        else:
            radial_unit = np.array([1.0, 0.0])

        per_ball_radial = max(radial_force / max(1.0, self.inputs.ball_count / 2.0), 1.0)
        radial_deflection = max(
            0.003,
            (per_ball_radial / self.combined_stiffness) ** (2.0 / 3.0),
        )
        axial_deflection = 0.0
        if abs(target[2]) > 0.0:
            axial_deflection = math.copysign(
                max(
                    0.003,
                    (abs(target[2]) / (self.combined_stiffness * self.inputs.ball_count))
                    ** (2.0 / 3.0),
                ),
                target[2],
            )

        base = np.array(
            [radial_deflection * radial_unit[0], radial_deflection * radial_unit[1], axial_deflection],
            dtype=float,
        )
        guesses = [base]
        for multiplier in (0.0, 0.5, 2.0, 5.0, 10.0, -1.0):
            guesses.append(base * multiplier)
        guesses.extend(
            [
                np.array([0.02, 0.0, 0.0]),
                np.array([-0.02, 0.0, 0.0]),
                np.array([0.0, 0.02, 0.0]),
                np.array([0.0, -0.02, 0.0]),
                np.array([0.0, 0.0, 0.02]),
                np.array([0.0, 0.0, -0.02]),
            ]
        )
        return guesses

    def _solve_equilibrium(
        self,
        transfer_coefficient: float,
        initial_guess: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray, bool]:
        target = self.inputs.target_vector()
        force_scale = max(1.0, float(np.linalg.norm(target, ord=2)))

        def residual(displacement: np.ndarray) -> np.ndarray:
            forces, _, _ = self._contact_state(displacement, transfer_coefficient)
            return (forces - target) / force_scale

        guesses = []
        if initial_guess is not None:
            guesses.append(initial_guess)
        guesses.extend(self._initial_guesses(target))

        best_solution = None
        for guess in guesses:
            solution = least_squares(
                residual,
                guess,
                x_scale=np.array([0.02, 0.02, 0.02]),
                xtol=1e-10,
                ftol=1e-10,
                gtol=1e-10,
                max_nfev=3000,
            )
            if best_solution is None or solution.cost < best_solution.cost:
                best_solution = solution

        displacement = best_solution.x
        calculated_load, _, _ = self._contact_state(displacement, transfer_coefficient)
        residual_force = calculated_load - target
        converged = bool(
            best_solution.success
            and np.max(np.abs(residual_force / force_scale)) < 1e-4
        )
        return displacement, residual_force, converged

    def _scenario(
        self,
        transfer_coefficient: float,
        baseline_damage_index: float | None = None,
        baseline_peak_load: float | None = None,
        initial_guess: np.ndarray | None = None,
    ) -> tuple[RoundnessScenarioResult, np.ndarray]:
        displacement, residual_force, converged = self._solve_equilibrium(
            transfer_coefficient,
            initial_guess=initial_guess,
        )
        _, details, damage_index = self._contact_state(
            displacement,
            transfer_coefficient,
            baseline_peak_load=baseline_peak_load,
        )
        active_details = [detail for detail in details if detail.normal_load_n > 0.0]
        peak_ball_load = max((detail.normal_load_n for detail in active_details), default=0.0)
        peak_ball_load_ratio = (
            peak_ball_load / baseline_peak_load
            if baseline_peak_load and baseline_peak_load > 0.0
            else 1.0
        )
        damage_ratio = (
            damage_index / baseline_damage_index
            if baseline_damage_index and baseline_damage_index > 0.0
            else 1.0
        )
        relative_life_ratio = 1.0 / damage_ratio if damage_ratio > 0.0 else float("inf")
        worst_detail = max(
            active_details,
            key=lambda detail: detail.normal_load_n,
            default=None,
        )
        scenario = RoundnessScenarioResult(
            transfer_coefficient=transfer_coefficient,
            deformation_peak_to_valley_um=self.roundness_peak_to_valley_mm
            * transfer_coefficient
            * 1000.0,
            displacement_x_um=displacement[0] * 1000.0,
            displacement_y_um=displacement[1] * 1000.0,
            displacement_z_um=displacement[2] * 1000.0,
            residual_force_n=float(np.linalg.norm(residual_force, ord=2)),
            solver_converged=converged,
            active_ball_count=len(active_details),
            peak_ball_load_n=peak_ball_load,
            peak_ball_load_ratio=peak_ball_load_ratio,
            damage_index=damage_index,
            damage_ratio=damage_ratio,
            relative_life_ratio=relative_life_ratio,
            contact_stress_index=peak_ball_load_ratio ** (1.0 / 3.0)
            if peak_ball_load_ratio > 0.0
            else 0.0,
            min_local_clearance_um=min(
                (detail.local_clearance_um for detail in details),
                default=0.0,
            ),
            worst_angle_deg=worst_detail.angle_deg if worst_detail else 0.0,
            details=details,
        )
        return scenario, displacement

    def calculate(self) -> SeatBoreRoundnessResult:
        baseline, displacement = self._scenario(0.0)
        baseline_details = [detail for detail in baseline.details if detail.normal_load_n > 0.0]
        baseline_peak_load = max(
            (detail.normal_load_n for detail in baseline_details),
            default=0.0,
        )
        baseline, displacement = self._scenario(
            0.0,
            baseline_damage_index=baseline.damage_index,
            baseline_peak_load=baseline_peak_load,
            initial_guess=displacement,
        )

        scenarios = []
        last_displacement = displacement
        for coefficient in self.inputs.transfer_coefficients:
            scenario, last_displacement = self._scenario(
                coefficient,
                baseline_damage_index=baseline.damage_index,
                baseline_peak_load=baseline_peak_load,
                initial_guess=last_displacement,
            )
            scenarios.append(scenario)

        return SeatBoreRoundnessResult(
            baseline=baseline,
            scenarios=scenarios,
            roundness_peak_to_valley_um=self.roundness_peak_to_valley_mm * 1000.0,
            centered_roundness_points=self.centered_points,
        )


def calculate_seat_bore_roundness(
    inputs: SeatBoreRoundnessInputs,
) -> SeatBoreRoundnessResult:
    return SeatBoreRoundnessModel(inputs).calculate()
