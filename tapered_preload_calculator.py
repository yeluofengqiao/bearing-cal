from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal


PreloadDirection = Literal["thinner_increases_preload", "thicker_increases_preload"]


@dataclass(frozen=True)
class TaperedPreloadInputs:
    zero_endplay_shim_mm: float
    minimum_hot_preload_n: float
    target_hot_preload_n: float
    left_bearing_stiffness_n_per_mm: float
    right_bearing_stiffness_n_per_mm: float
    housing_stiffness_n_per_mm: float
    shaft_stiffness_n_per_mm: float
    housing_alpha_per_c: float
    housing_effective_span_mm: float
    housing_delta_temp_c: float
    shim_step_mm: float
    preload_direction: PreloadDirection = "thinner_increases_preload"

    def __post_init__(self) -> None:
        positive_fields = {
            "zero_endplay_shim_mm": self.zero_endplay_shim_mm,
            "left_bearing_stiffness_n_per_mm": self.left_bearing_stiffness_n_per_mm,
            "right_bearing_stiffness_n_per_mm": self.right_bearing_stiffness_n_per_mm,
            "housing_stiffness_n_per_mm": self.housing_stiffness_n_per_mm,
            "shaft_stiffness_n_per_mm": self.shaft_stiffness_n_per_mm,
            "housing_alpha_per_c": self.housing_alpha_per_c,
            "housing_effective_span_mm": self.housing_effective_span_mm,
            "shim_step_mm": self.shim_step_mm,
        }
        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} 必须大于 0。")

        non_negative_fields = {
            "minimum_hot_preload_n": self.minimum_hot_preload_n,
            "target_hot_preload_n": self.target_hot_preload_n,
        }
        for name, value in non_negative_fields.items():
            if value < 0:
                raise ValueError(f"{name} 不能小于 0。")

        if self.target_hot_preload_n < self.minimum_hot_preload_n:
            raise ValueError("目标热态预紧力不能小于热态最小预紧力。")

        if self.preload_direction not in {
            "thinner_increases_preload",
            "thicker_increases_preload",
        }:
            raise ValueError("preload_direction 取值无效。")

    @property
    def preload_sign(self) -> float:
        return 1.0 if self.preload_direction == "thinner_increases_preload" else -1.0


@dataclass(frozen=True)
class DeflectionBreakdown:
    left_bearing_mm: float
    right_bearing_mm: float
    housing_mm: float
    shaft_mm: float
    total_mm: float


@dataclass(frozen=True)
class ShimPointResult:
    shim_mm: float
    preload_displacement_mm: float
    cold_preload_n: float
    hot_preload_n: float
    cold_clearance_mm: float
    hot_clearance_mm: float
    margin_to_min_hot_preload_n: float
    margin_to_target_hot_preload_n: float
    cold_deflection: DeflectionBreakdown
    hot_deflection: DeflectionBreakdown
    delta_from_nominal_mm: float
    meets_min_hot_preload: bool


@dataclass(frozen=True)
class TaperedPreloadResult:
    equivalent_stiffness_n_per_mm: float
    housing_thermal_growth_mm: float
    minimum_cold_preload_n: float
    target_cold_preload_n: float
    minimum_interference_mm: float
    target_interference_mm: float
    minimum_shim_mm: float
    nominal_shim_mm: float
    selected_shim_mm: float
    selected_point: ShimPointResult
    candidate_points: tuple[ShimPointResult, ...]


def equivalent_stiffness(inputs: TaperedPreloadInputs) -> float:
    return 1.0 / (
        1.0 / inputs.left_bearing_stiffness_n_per_mm
        + 1.0 / inputs.right_bearing_stiffness_n_per_mm
        + 1.0 / inputs.housing_stiffness_n_per_mm
        + 1.0 / inputs.shaft_stiffness_n_per_mm
    )


def housing_thermal_growth(inputs: TaperedPreloadInputs) -> float:
    return (
        inputs.housing_alpha_per_c
        * inputs.housing_effective_span_mm
        * inputs.housing_delta_temp_c
    )


def deflection_breakdown(
    inputs: TaperedPreloadInputs,
    preload_n: float,
) -> DeflectionBreakdown:
    if preload_n <= 0:
        return DeflectionBreakdown(0.0, 0.0, 0.0, 0.0, 0.0)

    left_bearing_mm = preload_n / inputs.left_bearing_stiffness_n_per_mm
    right_bearing_mm = preload_n / inputs.right_bearing_stiffness_n_per_mm
    housing_mm = preload_n / inputs.housing_stiffness_n_per_mm
    shaft_mm = preload_n / inputs.shaft_stiffness_n_per_mm
    total_mm = left_bearing_mm + right_bearing_mm + housing_mm + shaft_mm
    return DeflectionBreakdown(
        left_bearing_mm=left_bearing_mm,
        right_bearing_mm=right_bearing_mm,
        housing_mm=housing_mm,
        shaft_mm=shaft_mm,
        total_mm=total_mm,
    )


def shim_to_preload_displacement(
    inputs: TaperedPreloadInputs,
    shim_mm: float,
) -> float:
    return (inputs.zero_endplay_shim_mm - shim_mm) * inputs.preload_sign


def evaluate_shim(
    inputs: TaperedPreloadInputs,
    shim_mm: float,
    *,
    nominal_shim_mm: float | None = None,
) -> ShimPointResult:
    k_eq = equivalent_stiffness(inputs)
    thermal_growth_mm = housing_thermal_growth(inputs)
    preload_displacement_mm = shim_to_preload_displacement(inputs, shim_mm)

    cold_preload_n = max(preload_displacement_mm, 0.0) * k_eq
    cold_clearance_mm = max(-preload_displacement_mm, 0.0)

    hot_displacement_mm = preload_displacement_mm - thermal_growth_mm
    hot_preload_n = max(hot_displacement_mm, 0.0) * k_eq
    hot_clearance_mm = max(-hot_displacement_mm, 0.0)

    return ShimPointResult(
        shim_mm=shim_mm,
        preload_displacement_mm=preload_displacement_mm,
        cold_preload_n=cold_preload_n,
        hot_preload_n=hot_preload_n,
        cold_clearance_mm=cold_clearance_mm,
        hot_clearance_mm=hot_clearance_mm,
        margin_to_min_hot_preload_n=hot_preload_n - inputs.minimum_hot_preload_n,
        margin_to_target_hot_preload_n=hot_preload_n - inputs.target_hot_preload_n,
        cold_deflection=deflection_breakdown(inputs, cold_preload_n),
        hot_deflection=deflection_breakdown(inputs, hot_preload_n),
        delta_from_nominal_mm=0.0 if nominal_shim_mm is None else shim_mm - nominal_shim_mm,
        meets_min_hot_preload=hot_preload_n >= inputs.minimum_hot_preload_n,
    )


def calculate_tapered_preload(inputs: TaperedPreloadInputs) -> TaperedPreloadResult:
    k_eq = equivalent_stiffness(inputs)
    thermal_growth_mm = housing_thermal_growth(inputs)

    minimum_interference_mm = thermal_growth_mm + inputs.minimum_hot_preload_n / k_eq
    target_interference_mm = thermal_growth_mm + inputs.target_hot_preload_n / k_eq

    minimum_shim_mm = inputs.zero_endplay_shim_mm - inputs.preload_sign * minimum_interference_mm
    nominal_shim_mm = inputs.zero_endplay_shim_mm - inputs.preload_sign * target_interference_mm

    candidate_points = tuple(
        evaluate_shim(inputs, shim_mm, nominal_shim_mm=nominal_shim_mm)
        for shim_mm in build_candidate_thicknesses(nominal_shim_mm, inputs.shim_step_mm)
    )
    selected_point = select_recommended_point(inputs, nominal_shim_mm, candidate_points)

    return TaperedPreloadResult(
        equivalent_stiffness_n_per_mm=k_eq,
        housing_thermal_growth_mm=thermal_growth_mm,
        minimum_cold_preload_n=inputs.minimum_hot_preload_n + k_eq * thermal_growth_mm,
        target_cold_preload_n=inputs.target_hot_preload_n + k_eq * thermal_growth_mm,
        minimum_interference_mm=minimum_interference_mm,
        target_interference_mm=target_interference_mm,
        minimum_shim_mm=minimum_shim_mm,
        nominal_shim_mm=nominal_shim_mm,
        selected_shim_mm=selected_point.shim_mm,
        selected_point=selected_point,
        candidate_points=candidate_points,
    )


def build_candidate_thicknesses(
    nominal_shim_mm: float,
    shim_step_mm: float,
    *,
    count: int = 5,
) -> tuple[float, ...]:
    half_span = count // 2
    precision = decimal_places(shim_step_mm)
    center_index = math.floor(nominal_shim_mm / shim_step_mm + 0.5)
    values: list[float] = []

    for offset in range(-half_span, half_span + 1):
        candidate_index = center_index + offset
        candidate_mm = candidate_index * shim_step_mm
        if candidate_mm <= 0:
            continue
        rounded_candidate = round(candidate_mm, precision)
        if rounded_candidate not in values:
            values.append(rounded_candidate)

    return tuple(values)


def select_recommended_point(
    inputs: TaperedPreloadInputs,
    nominal_shim_mm: float,
    candidate_points: tuple[ShimPointResult, ...],
) -> ShimPointResult:
    return min(
        candidate_points,
        key=lambda point: (
            0 if point.meets_min_hot_preload else 1,
            abs(point.delta_from_nominal_mm),
            inputs.preload_sign * (point.shim_mm - nominal_shim_mm),
        ),
    )


def decimal_places(step: float) -> int:
    text = f"{step:.12f}".rstrip("0").rstrip(".")
    if "." not in text:
        return 0
    return len(text.split(".")[1])
