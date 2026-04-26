import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.special import ellipe, ellipk


FORCE_LABELS = ["Fx (N)", "Fy (N)", "Fz (N)", "Mx (N·mm)", "My (N·mm)"]
DOF_LABELS = ["x (mm)", "y (mm)", "z (mm)", "theta_x (rad)", "theta_y (rad)"]


@dataclass
class BallContactDetail:
    index: int
    angle_deg: float
    normal_load_n: float
    normal_approach_um: float
    contact_angle_deg: float
    radial_force_n: float
    axial_force_n: float

    def to_dict(self):
        return asdict(self)


@dataclass
class BallBearingStiffnessInputs:
    ball_count: int = 8
    ball_diameter_mm: float = 15.875
    pitch_diameter_mm: float = 66.5
    inner_groove_radius_mm: float = 8.075
    outer_groove_radius_mm: float = 8.3125
    inner_raceway_diameter_mm: float = 50.625
    outer_raceway_diameter_mm: float = 82.375
    diametral_clearance_mm: float = 0.0
    elastic_modulus_mpa: float = 206000.0
    poisson_ratio: float = 0.3
    fx_n: float = 1000.0
    fy_n: float = 0.0
    fz_n: float = 500.0
    mx_nmm: float = 0.0
    my_nmm: float = 0.0
    translation_step_um: float = 1.0
    rotation_step_urad: float = 10.0

    @property
    def inner_curvature_ratio(self):
        return self.inner_groove_radius_mm / self.ball_diameter_mm

    @property
    def outer_curvature_ratio(self):
        return self.outer_groove_radius_mm / self.ball_diameter_mm

    @property
    def groove_center_distance_mm(self):
        return (
            self.inner_groove_radius_mm
            + self.outer_groove_radius_mm
            - self.ball_diameter_mm
        )

    @property
    def pitch_radius_mm(self):
        return 0.5 * self.pitch_diameter_mm

    @property
    def raceway_derived_clearance_mm(self):
        return (
            self.outer_raceway_diameter_mm
            - self.inner_raceway_diameter_mm
            - 2.0 * self.ball_diameter_mm
        )

    @property
    def effective_modulus_mpa(self):
        # Hertz contact uses the reduced modulus of two elastic bodies.
        # For a steel ball and steel race with the same E and nu:
        # 1 / E* = 2 * (1 - nu^2) / E.
        return self.elastic_modulus_mpa / (2.0 * (1.0 - self.poisson_ratio**2))

    def target_vector(self):
        return np.array(
            [self.fx_n, self.fy_n, self.fz_n, self.mx_nmm, self.my_nmm],
            dtype=float,
        )

    def validate(self):
        positive_fields = {
            "ball_diameter_mm": self.ball_diameter_mm,
            "pitch_diameter_mm": self.pitch_diameter_mm,
            "inner_groove_radius_mm": self.inner_groove_radius_mm,
            "outer_groove_radius_mm": self.outer_groove_radius_mm,
            "inner_raceway_diameter_mm": self.inner_raceway_diameter_mm,
            "outer_raceway_diameter_mm": self.outer_raceway_diameter_mm,
            "elastic_modulus_mpa": self.elastic_modulus_mpa,
            "translation_step_um": self.translation_step_um,
            "rotation_step_urad": self.rotation_step_urad,
        }
        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} 必须大于 0。")

        if self.ball_count < 3:
            raise ValueError("钢球数至少需要 3。")
        if self.pitch_diameter_mm <= self.ball_diameter_mm:
            raise ValueError("节圆直径必须大于钢球直径。")
        if self.diametral_clearance_mm < 0:
            raise ValueError("直径游隙不能为负数。")
        if not 0.0 < self.poisson_ratio < 0.5:
            raise ValueError("泊松比需要在 0 和 0.5 之间。")
        if self.groove_center_distance_mm <= 0:
            raise ValueError("内外圈沟曲率半径之和必须大于钢球直径。")


@dataclass
class BallBearingStiffnessResult:
    displacement_vector: list[float]
    load_vector: list[float]
    residual_vector: list[float]
    stiffness_matrix: list[list[float]]
    solver_converged: bool
    solver_message: str
    contact_stiffness_n_per_mm15: float
    inner_contact_stiffness_n_per_mm15: float
    outer_contact_stiffness_n_per_mm15: float
    inner_curvature_ratio: float
    outer_curvature_ratio: float
    raceway_derived_clearance_mm: float
    active_ball_count: int
    peak_ball_load_n: float
    max_contact_angle_deg: float
    symmetry_error_pct: float
    details: list[BallContactDetail]

    def to_dict(self):
        payload = asdict(self)
        payload["details"] = [detail.to_dict() for detail in self.details]
        return payload


class BallBearingStiffnessModel:
    def __init__(self, inputs=None):
        self.inputs = inputs or BallBearingStiffnessInputs()
        self.inputs.validate()
        self.angles = np.linspace(0.0, 2.0 * np.pi, self.inputs.ball_count, endpoint=False)
        (
            self.inner_stiffness,
            self.inner_k_ratio,
            self.inner_sum_rho,
            self.inner_e_value,
        ) = self._single_contact_stiffness(is_inner=True)
        (
            self.outer_stiffness,
            self.outer_k_ratio,
            self.outer_sum_rho,
            self.outer_e_value,
        ) = self._single_contact_stiffness(is_inner=False)
        self.combined_stiffness = 1.0 / (
            ((1.0 / self.inner_stiffness) ** (2.0 / 3.0))
            + ((1.0 / self.outer_stiffness) ** (2.0 / 3.0))
        ) ** 1.5

    def _solve_elliptical_param(self, cos_tau):
        cos_tau = float(np.clip(cos_tau, 1e-6, 0.9999))

        def objective(eccentricity):
            if eccentricity <= 0.0 or eccentricity >= 1.0:
                return 1.0
            k_val = ellipk(eccentricity**2)
            e_val = ellipe(eccentricity**2)
            return (
                (
                    (2.0 - eccentricity**2) * e_val
                    - 2.0 * (1.0 - eccentricity**2) * k_val
                )
                / (eccentricity**2 * e_val)
                - cos_tau
            )

        solution = least_squares(
            lambda value: [objective(value[0])],
            [0.85],
            bounds=([1e-5], [0.99999]),
            xtol=1e-12,
            ftol=1e-12,
            gtol=1e-12,
        )
        eccentricity = float(solution.x[0])
        k_val = ellipk(eccentricity**2)
        e_val = ellipe(eccentricity**2)
        k_ratio = 1.0 / math.sqrt(1.0 - eccentricity**2)
        return k_val, e_val, k_ratio

    def _single_contact_stiffness(self, is_inner):
        p = self.inputs
        rho11 = rho12 = 2.0 / p.ball_diameter_mm
        if is_inner:
            rho21 = -1.0 / p.inner_groove_radius_mm
            rho22 = -2.0 / (p.pitch_diameter_mm - p.ball_diameter_mm)
        else:
            rho21 = -1.0 / p.outer_groove_radius_mm
            rho22 = 2.0 / (p.pitch_diameter_mm + p.ball_diameter_mm)

        sum_rho = rho11 + rho12 + rho21 + rho22
        if sum_rho <= 0:
            location = "内圈" if is_inner else "外圈"
            raise ValueError(f"{location}接触曲率组合无效，请复核沟曲率半径和节圆直径。")

        diff_rho = (rho11 - rho12) + (rho21 - rho22)
        cos_tau = abs(diff_rho) / sum_rho
        k_el, e_el, k_ratio = self._solve_elliptical_param(cos_tau)

        q_test = 1.0
        term_common = (3.0 * q_test) / (2.0 * sum_rho * p.effective_modulus_mpa)
        a_star = (2.0 * (k_ratio**2) * e_el / np.pi) ** (1.0 / 3.0)
        delta_star = (2.0 * k_el) / (np.pi * a_star)
        delta_1n = delta_star * (sum_rho / 2.0) * (term_common ** (2.0 / 3.0))
        contact_stiffness = 1.0 / (delta_1n**1.5)
        return float(contact_stiffness), float(k_ratio), float(sum_rho), float(e_el)

    def _contact_state(self, displacement):
        p = self.inputs
        dx, dy, dz, theta_x, theta_y = np.asarray(displacement, dtype=float)
        base_distance = p.groove_center_distance_mm
        pitch_radius = p.pitch_radius_mm
        clearance_allowance = 0.5 * p.diametral_clearance_mm
        force_vector = np.zeros(5, dtype=float)
        details = []

        for index, psi in enumerate(self.angles, start=1):
            cos_psi = math.cos(psi)
            sin_psi = math.sin(psi)
            radial_shift = dx * cos_psi + dy * sin_psi
            axial_shift = dz + pitch_radius * (theta_x * sin_psi - theta_y * cos_psi)
            radial_gap = base_distance + radial_shift
            center_distance = math.hypot(radial_gap, axial_shift)
            if center_distance <= 1e-12:
                details.append(
                    BallContactDetail(
                        index=index,
                        angle_deg=math.degrees(psi),
                        normal_load_n=0.0,
                        normal_approach_um=0.0,
                        contact_angle_deg=0.0,
                        radial_force_n=0.0,
                        axial_force_n=0.0,
                    )
                )
                continue

            normal_approach = center_distance - base_distance - clearance_allowance
            if normal_approach <= 0.0:
                details.append(
                    BallContactDetail(
                        index=index,
                        angle_deg=math.degrees(psi),
                        normal_load_n=0.0,
                        normal_approach_um=0.0,
                        contact_angle_deg=0.0,
                        radial_force_n=0.0,
                        axial_force_n=0.0,
                    )
                )
                continue

            normal_load = self.combined_stiffness * (normal_approach**1.5)
            radial_force = normal_load * radial_gap / center_distance
            axial_force = normal_load * axial_shift / center_distance

            force_vector[0] += radial_force * cos_psi
            force_vector[1] += radial_force * sin_psi
            force_vector[2] += axial_force
            force_vector[3] += pitch_radius * sin_psi * axial_force
            force_vector[4] += -pitch_radius * cos_psi * axial_force

            details.append(
                BallContactDetail(
                    index=index,
                    angle_deg=math.degrees(psi),
                    normal_load_n=float(normal_load),
                    normal_approach_um=float(normal_approach * 1000.0),
                    contact_angle_deg=float(math.degrees(math.atan2(axial_shift, radial_gap))),
                    radial_force_n=float(radial_force),
                    axial_force_n=float(axial_force),
                )
            )

        return force_vector, details

    def force_vector(self, displacement):
        forces, _ = self._contact_state(displacement)
        return forces

    def _residual_scales(self, target):
        force_scale = max(1.0, float(np.linalg.norm(target[:3], ord=2)))
        moment_scale = max(1.0, float(np.linalg.norm(target[3:], ord=2)), force_scale * self.inputs.pitch_radius_mm)
        return np.array([force_scale, force_scale, force_scale, moment_scale, moment_scale])

    def _initial_guesses(self, target):
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
                    (abs(target[2]) / (self.combined_stiffness * self.inputs.ball_count)) ** (2.0 / 3.0),
                ),
                target[2],
            )

        theta_x = math.copysign(2e-4, target[3]) if abs(target[3]) > 0.0 else 0.0
        theta_y = math.copysign(2e-4, target[4]) if abs(target[4]) > 0.0 else 0.0
        base = np.array(
            [
                radial_deflection * radial_unit[0],
                radial_deflection * radial_unit[1],
                axial_deflection,
                theta_x,
                theta_y,
            ],
            dtype=float,
        )

        guesses = [base]
        for multiplier in (0.5, 2.0, 5.0, 10.0):
            guesses.append(base * multiplier)
        guesses.append(np.array([0.02, 0.0, 0.02, 0.0, 0.0]))
        guesses.append(np.array([-0.02, 0.0, 0.02, 0.0, 0.0]))
        guesses.append(np.array([0.0, 0.02, 0.02, 0.0, 0.0]))
        guesses.append(np.array([0.0, 0.0, 0.02, 2e-4, 0.0]))
        guesses.append(np.array([0.0, 0.0, 0.02, 0.0, 2e-4]))
        return guesses

    def solve_equilibrium(self):
        target = self.inputs.target_vector()
        scales = self._residual_scales(target)

        def residual(displacement):
            return (self.force_vector(displacement) - target) / scales

        best_solution = None
        for guess in self._initial_guesses(target):
            solution = least_squares(
                residual,
                guess,
                x_scale=np.array([0.02, 0.02, 0.02, 2e-4, 2e-4]),
                xtol=1e-10,
                ftol=1e-10,
                gtol=1e-10,
                max_nfev=3000,
            )
            if best_solution is None or solution.cost < best_solution.cost:
                best_solution = solution

        displacement = best_solution.x
        calculated_load = self.force_vector(displacement)
        residual_load = calculated_load - target
        scaled_residual = residual_load / scales
        converged = bool(best_solution.success and np.max(np.abs(scaled_residual)) < 1e-4)
        return displacement, calculated_load, residual_load, converged, best_solution.message

    def stiffness_matrix(self, displacement):
        step_translation = self.inputs.translation_step_um * 1e-3
        step_rotation = self.inputs.rotation_step_urad * 1e-6
        steps = np.array(
            [
                step_translation,
                step_translation,
                step_translation,
                step_rotation,
                step_rotation,
            ],
            dtype=float,
        )
        matrix = np.zeros((5, 5), dtype=float)
        displacement = np.asarray(displacement, dtype=float)

        for column, step in enumerate(steps):
            perturbation = np.zeros(5, dtype=float)
            perturbation[column] = step
            plus = self.force_vector(displacement + perturbation)
            minus = self.force_vector(displacement - perturbation)
            matrix[:, column] = (plus - minus) / (2.0 * step)

        return matrix

    def calculate(self):
        displacement, load, residual, converged, message = self.solve_equilibrium()
        matrix = self.stiffness_matrix(displacement)
        _, details = self._contact_state(displacement)
        active_details = [detail for detail in details if detail.normal_load_n > 0.0]
        peak_ball_load = max((detail.normal_load_n for detail in active_details), default=0.0)
        max_contact_angle = max(
            (abs(detail.contact_angle_deg) for detail in active_details),
            default=0.0,
        )
        matrix_norm = float(np.linalg.norm(matrix, ord="fro"))
        symmetry_error = 0.0
        if matrix_norm > 0.0:
            symmetry_error = float(
                np.linalg.norm(matrix - matrix.T, ord="fro") / matrix_norm * 100.0
            )

        return BallBearingStiffnessResult(
            displacement_vector=[float(value) for value in displacement],
            load_vector=[float(value) for value in load],
            residual_vector=[float(value) for value in residual],
            stiffness_matrix=[
                [float(value) for value in row]
                for row in matrix
            ],
            solver_converged=converged,
            solver_message=str(message),
            contact_stiffness_n_per_mm15=float(self.combined_stiffness),
            inner_contact_stiffness_n_per_mm15=float(self.inner_stiffness),
            outer_contact_stiffness_n_per_mm15=float(self.outer_stiffness),
            inner_curvature_ratio=float(self.inputs.inner_curvature_ratio),
            outer_curvature_ratio=float(self.inputs.outer_curvature_ratio),
            raceway_derived_clearance_mm=float(self.inputs.raceway_derived_clearance_mm),
            active_ball_count=len(active_details),
            peak_ball_load_n=float(peak_ball_load),
            max_contact_angle_deg=float(max_contact_angle),
            symmetry_error_pct=symmetry_error,
            details=details,
        )


def calculate_ball_bearing_stiffness(inputs):
    return BallBearingStiffnessModel(inputs).calculate()
