import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import fsolve
from scipy.special import ellipe, ellipk


def astm_d341_kinematic_viscosity_cst(nu_40_cst, nu_100_cst, temperature_c):
    if nu_40_cst <= 0 or nu_100_cst <= 0:
        raise ValueError("ASTM D341 黏度换算要求 nu_40_cst 和 nu_100_cst 都大于 0。")

    temperature_k = temperature_c + 273.15
    if temperature_k <= 0:
        raise ValueError("油温必须高于绝对零度。")

    x_40 = math.log10(40 + 273.15)
    x_100 = math.log10(100 + 273.15)
    y_40 = math.log10(math.log10(nu_40_cst + 0.7))
    y_100 = math.log10(math.log10(nu_100_cst + 0.7))

    slope = (y_40 - y_100) / (x_100 - x_40)
    intercept = y_40 + slope * x_40
    y_temp = intercept - slope * math.log10(temperature_k)
    return (10 ** (10**y_temp)) - 0.7


def dynamic_viscosity_from_kinematic_cst(nu_cst, density_kg_m3):
    if nu_cst <= 0 or density_kg_m3 <= 0:
        raise ValueError("运动黏度和密度都必须大于 0。")
    return nu_cst * 1e-6 * density_kg_m3


def kinematic_viscosity_from_dynamic_pa_s(dynamic_viscosity_pa_s, density_kg_m3):
    if dynamic_viscosity_pa_s <= 0 or density_kg_m3 <= 0:
        raise ValueError("动力黏度和密度都必须大于 0。")
    return dynamic_viscosity_pa_s / density_kg_m3 * 1e6


def reference_kinematic_viscosity_cst(speed_rpm, pitch_diameter_mm):
    if speed_rpm <= 0 or pitch_diameter_mm <= 0:
        return 0.0
    if speed_rpm < 1000:
        return 45000 * (speed_rpm**-0.83) * (pitch_diameter_mm**-0.5)
    return 4500 * (speed_rpm**-0.5) * (pitch_diameter_mm**-0.5)


@dataclass
class BallDetail:
    angle_deg: float
    load_q_n: float
    max_stress_mpa: float
    truncation_ratio_pct: float
    film_thickness_um: float
    outer_film_thickness_um: float
    capacitance_pf: float
    contact_angle_deg: float
    ehl_friction_force_n: float
    ehl_friction_torque_nmm: float
    traction_coeff_inner: float
    traction_coeff_outer: float
    lambda_value: float
    outer_lambda_value: float

    def to_dict(self):
        return asdict(self)


@dataclass
class CalculationResult:
    oil_capacitance_pf: float
    pps_capacitance_pf: float
    system_capacitance_pf: float
    ehl_friction_torque_nmm: float
    ehl_friction_torque_nm: float
    radial_displacement_mm: float
    axial_displacement_mm: float
    operating_kinematic_viscosity_cst: float
    reference_kinematic_viscosity_cst: float
    kappa: float
    minimum_film_thickness_um: float
    minimum_outer_film_thickness_um: float
    minimum_lambda: float
    minimum_outer_lambda: float
    solver_converged: bool
    details: list[BallDetail]


@dataclass
class BearingParameters:
    d: float = 40.0
    D: float = 80.0
    B: float = 18.0
    Dw: float = 11.906
    Dm: float = 60.0
    Z: int = 9
    fi: float = 0.505
    fe: float = 0.525
    Pd: float = 0.010
    H_i: float = 2.3812
    E: float = 2.06e5
    nu: float = 0.3
    eta0: float = 0.015
    oil_density_kg_m3: float = 850.0
    composite_roughness_um: float = 0.052
    alpha: float = 1.5e-8
    eps_r: float = 2.1
    t_pps: float = 2.0
    eps_r_pps: float = 4.2
    slip_ratio_inner: float = 0.02
    slip_ratio_outer: float = 0.02
    shear_limit_factor: float = 0.03
    max_shear_stress_mpa: float = 80.0

    @property
    def L(self):
        return self.Dw * (self.fi + self.fe - 1)

    @property
    def E_prime(self):
        return self.E / (1 - self.nu**2)

    @property
    def eps_0(self):
        return 8.854e-12

    def to_dict(self):
        return asdict(self)

    def validate(self):
        positive_fields = {
            "d": self.d,
            "D": self.D,
            "B": self.B,
            "Dw": self.Dw,
            "Dm": self.Dm,
            "fi": self.fi,
            "fe": self.fe,
            "H_i": self.H_i,
            "E": self.E,
            "eta0": self.eta0,
            "oil_density_kg_m3": self.oil_density_kg_m3,
            "composite_roughness_um": self.composite_roughness_um,
            "alpha": self.alpha,
            "eps_r": self.eps_r,
            "t_pps": self.t_pps,
            "eps_r_pps": self.eps_r_pps,
            "max_shear_stress_mpa": self.max_shear_stress_mpa,
        }
        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} 必须大于 0。")

        if self.Z < 1:
            raise ValueError("钢球数 Z 必须至少为 1。")
        if self.Pd < 0:
            raise ValueError("直径游隙 Pd 不能为负数。")
        if self.slip_ratio_inner < 0 or self.slip_ratio_outer < 0:
            raise ValueError("滑滚比 slip_ratio_inner/slip_ratio_outer 不能为负数。")
        if self.shear_limit_factor <= 0 or self.shear_limit_factor >= 1:
            raise ValueError("shear_limit_factor 需要在 0 和 1 之间。")
        if not 0 < self.nu < 0.5:
            raise ValueError("泊松比 nu 需要在 0 和 0.5 之间。")
        if self.D <= self.d:
            raise ValueError("外径 D 必须大于内径 d。")
        if self.Dm <= self.Dw:
            raise ValueError("节圆直径 Dm 必须大于钢球直径 Dw。")
        if self.D <= 2 * self.t_pps:
            raise ValueError("PPS 厚度过大，导致包塑层内径无效。")
        if self.fi + self.fe <= 1:
            raise ValueError("沟道曲率系数 fi + fe 必须大于 1。")

        r_inner = self.fi * self.Dw
        if self.H_i >= 2 * r_inner:
            raise ValueError("内圈沟道深度 H_i 过大，超过几何允许范围。")


class BearingCapacitanceModel:
    def __init__(self, params=None):
        self.params = params or BearingParameters()
        self.params.validate()

    def _solve_elliptical_param(self, cos_tau):
        cos_tau = np.clip(cos_tau, 1e-6, 0.9999)

        def objective(e):
            if e <= 0 or e >= 1:
                return 1.0
            k_val = ellipk(e**2)
            e_val = ellipe(e**2)
            return (
                ((2 - e**2) * e_val - 2 * (1 - e**2) * k_val) / (e**2 * e_val)
                - cos_tau
            )

        e_sol = fsolve(objective, 0.9)[0]
        k_val = ellipk(e_sol**2)
        e_val = ellipe(e_sol**2)
        k_ratio = 1 / np.sqrt(1 - e_sol**2)
        return k_val, e_val, k_ratio

    def get_contact_stiffness(self, is_inner):
        p = self.params
        rho11 = rho12 = 2 / p.Dw
        if is_inner:
            rho21 = -1 / (p.fi * p.Dw)
            rho22 = -2 / (p.Dm - p.Dw)
        else:
            rho21 = -1 / (p.fe * p.Dw)
            rho22 = 2 / (p.Dm + p.Dw)

        sum_rho = rho11 + rho12 + rho21 + rho22
        diff_rho = (rho11 - rho12) + (rho21 - rho22)
        cos_tau = abs(diff_rho) / sum_rho

        k_el, e_el, k_hd = self._solve_elliptical_param(cos_tau)

        q_test = 1.0
        term_common_1n = (3 * q_test) / (2 * sum_rho * p.E_prime)
        a_star = (2 * (k_hd**2) * e_el / np.pi) ** (1 / 3)
        delta_star = (2 * k_el) / (np.pi * a_star)

        delta_1n = delta_star * (sum_rho / 2) * (term_common_1n ** (2 / 3))
        k_calc = 1.0 / (delta_1n**1.5)
        rx_mm = 1.0 / (rho12 + rho22)

        return k_calc, k_hd, sum_rho, e_el, rx_mm

    def _get_hertz_params(self, q, sum_rho, k_ratio, e_val):
        if q <= 1e-5:
            return 0.0, 0.0, 0.0, 0.0

        term_common = (3 * q) / (2 * sum_rho * self.params.E_prime)
        a_star = (2 * (k_ratio**2) * e_val / np.pi) ** (1 / 3)
        b_star = (2 * e_val / (np.pi * k_ratio)) ** (1 / 3)

        a = a_star * (term_common ** (1 / 3))
        b = b_star * (term_common ** (1 / 3))
        area = np.pi * a * b
        p_max = (1.5 * q) / area

        return area, a, b, p_max

    def _central_film_thickness_mm(self, q, rx_m, u_vel, k_hd):
        if q <= 1e-5 or rx_m <= 0 or u_vel <= 0:
            return 0.0

        p = self.params
        g_param = p.alpha * (p.E_prime * 1e6)
        u_dimless = (p.eta0 * u_vel) / (p.E_prime * 1e6 * rx_m)
        w_dimless = q / ((p.E_prime * 1e6) * rx_m**2)
        k_effect = 1 - 0.61 * np.exp(-0.73 * k_hd)
        h_dimless = (
            2.69
            * (u_dimless**0.67)
            * (g_param**0.53)
            * (w_dimless**-0.067)
            * k_effect
        )
        return h_dimless * rx_m * 1000

    def _effective_viscosity(self, mean_pressure_pa):
        pressure_term = np.clip(self.params.alpha * mean_pressure_pa, 0.0, 25.0)
        # 直接使用 Barus 指数黏度会显著高估简化 Couette 剪切下的牵引应力，
        # 这里对压黏项做阻尼，保留高压增黏趋势，同时避免力矩失真到非工程量级。
        return self.params.eta0 * np.exp(np.sqrt(pressure_term))

    def _ehl_shear_stress_pa(self, sliding_speed, film_thickness_m, mean_pressure_pa):
        if sliding_speed <= 0 or film_thickness_m <= 0 or mean_pressure_pa <= 0:
            return 0.0

        eta_eff = self._effective_viscosity(mean_pressure_pa)
        tau_newton = eta_eff * sliding_speed / film_thickness_m
        tau_limit = min(
            self.params.shear_limit_factor * mean_pressure_pa,
            self.params.max_shear_stress_mpa * 1e6,
        )
        if tau_limit <= 0:
            return 0.0
        return tau_limit * np.tanh(tau_newton / tau_limit)

    def calculate(self, fr, fa, speed_rpm):
        if fr < 0 or fa < 0 or speed_rpm < 0:
            raise ValueError("Fr、Fa、speed_rpm 不能为负数。")

        p = self.params
        operating_kinematic_viscosity_cst = kinematic_viscosity_from_dynamic_pa_s(
            p.eta0, p.oil_density_kg_m3
        )
        reference_kinematic_viscosity = reference_kinematic_viscosity_cst(
            speed_rpm, p.Dm
        )
        kappa = 0.0
        if reference_kinematic_viscosity > 0:
            kappa = operating_kinematic_viscosity_cst / reference_kinematic_viscosity

        ki, ki_hd, sum_rho_i, e_val_i, rx_i_mm = self.get_contact_stiffness(
            is_inner=True
        )
        ke, ke_hd, sum_rho_e, e_val_e, rx_e_mm = self.get_contact_stiffness(
            is_inner=False
        )

        k_tot = 1 / (((1 / ki) ** (2 / 3) + (1 / ke) ** (2 / 3)) ** 1.5)
        angles = np.linspace(0, 2 * np.pi, p.Z, endpoint=False)

        def equilibrium_equations(vars_um):
            dr = vars_um[0] * 1e-3
            da = vars_um[1] * 1e-3
            fx = 0.0
            fz = 0.0
            for psi in angles:
                term_r = p.L + dr * np.cos(psi)
                term_a = da
                l_new = np.sqrt(term_r**2 + term_a**2)
                delta = l_new - p.L - (p.Pd / 2)
                if delta > 0:
                    q = k_tot * delta**1.5
                    fx += q * (term_r / l_new) * np.cos(psi)
                    fz += q * (term_a / l_new)
            return [fx - fr, fz - fa]

        sol_um, _, ier, _ = fsolve(
            equilibrium_equations,
            [50.0, 100.0],
            full_output=True,
        )
        dr_mm = sol_um[0] * 1e-3
        da_mm = sol_um[1] * 1e-3

        total_oil_cap = 0.0
        total_ehl_torque_nm = 0.0
        details = []
        u_vel_i = (np.pi * speed_rpm * p.Dm / 120) * (1 - (p.Dw / p.Dm) ** 2) / 1000
        u_vel_e = (np.pi * speed_rpm * p.Dm / 120) * (1 + (p.Dw / p.Dm) ** 2) / 1000
        delta_u_i = p.slip_ratio_inner * u_vel_i
        delta_u_e = p.slip_ratio_outer * u_vel_e
        pitch_radius_m = 0.5 * p.Dm / 1000

        r_inner = p.fi * p.Dw
        theta_edge_i = np.arccos(1.0 - p.H_i / r_inner)

        for psi in angles:
            term_r = p.L + dr_mm * np.cos(psi)
            term_a = da_mm
            l_new = np.sqrt(term_r**2 + term_a**2)
            delta = l_new - p.L - (p.Pd / 2)

            if delta <= 0:
                details.append(
                    BallDetail(
                        angle_deg=float(np.degrees(psi)),
                        load_q_n=0.0,
                        max_stress_mpa=0.0,
                        truncation_ratio_pct=0.0,
                        film_thickness_um=0.0,
                        outer_film_thickness_um=0.0,
                        capacitance_pf=0.0,
                        contact_angle_deg=0.0,
                        ehl_friction_force_n=0.0,
                        ehl_friction_torque_nmm=0.0,
                        traction_coeff_inner=0.0,
                        traction_coeff_outer=0.0,
                        lambda_value=0.0,
                        outer_lambda_value=0.0,
                    )
                )
                continue

            q = k_tot * delta**1.5
            alpha_contact = np.arcsin(term_a / l_new)

            rx_i = rx_i_mm / 1000
            area_i, a_i, _, pmax_i = self._get_hertz_params(q, sum_rho_i, ki_hd, e_val_i)
            h_i = self._central_film_thickness_mm(q, rx_i, u_vel_i, ki_hd)
            inner_film_um = h_i * 1000
            lambda_i = inner_film_um / p.composite_roughness_um
            c_in = 0.0
            if h_i > 0:
                c_in = (p.eps_0 * p.eps_r * area_i * 1e-6) / (h_i * 1e-3) * 1e12

            s_avail_i = r_inner * (theta_edge_i - alpha_contact)
            if a_i > s_avail_i:
                trunc_ratio_i = ((a_i - s_avail_i) / (2 * a_i)) * 100.0
            else:
                trunc_ratio_i = 0.0

            rx_e = rx_e_mm / 1000
            area_e, _, _, _ = self._get_hertz_params(q, sum_rho_e, ke_hd, e_val_e)
            h_e = self._central_film_thickness_mm(q, rx_e, u_vel_e, ke_hd)
            outer_film_um = h_e * 1000
            lambda_e = outer_film_um / p.composite_roughness_um
            c_out = 0.0
            if h_e > 0:
                c_out = (p.eps_0 * p.eps_r * area_e * 1e-6) / (h_e * 1e-3) * 1e12

            area_i_m2 = area_i * 1e-6
            area_e_m2 = area_e * 1e-6
            mean_pressure_i_pa = q / area_i_m2 if area_i_m2 > 0 else 0.0
            mean_pressure_e_pa = q / area_e_m2 if area_e_m2 > 0 else 0.0
            tau_i = self._ehl_shear_stress_pa(delta_u_i, h_i * 1e-3, mean_pressure_i_pa)
            tau_e = self._ehl_shear_stress_pa(delta_u_e, h_e * 1e-3, mean_pressure_e_pa)
            friction_force_i = tau_i * area_i_m2
            friction_force_e = tau_e * area_e_m2
            friction_force_ball = friction_force_i + friction_force_e
            ball_torque_nm = friction_force_ball * pitch_radius_m
            total_ehl_torque_nm += ball_torque_nm

            if c_in > 0 and c_out > 0:
                c_ball = 1 / (1 / c_in + 1 / c_out)
            else:
                c_ball = 0.0
            total_oil_cap += c_ball

            details.append(
                BallDetail(
                    angle_deg=float(np.degrees(psi)),
                    load_q_n=float(q),
                    max_stress_mpa=float(pmax_i),
                    truncation_ratio_pct=float(trunc_ratio_i),
                    film_thickness_um=float(inner_film_um),
                    outer_film_thickness_um=float(outer_film_um),
                    capacitance_pf=float(c_ball),
                    contact_angle_deg=float(np.degrees(alpha_contact)),
                    ehl_friction_force_n=float(friction_force_ball),
                    ehl_friction_torque_nmm=float(ball_torque_nm * 1000),
                    traction_coeff_inner=float(friction_force_i / q),
                    traction_coeff_outer=float(friction_force_e / q),
                    lambda_value=float(lambda_i),
                    outer_lambda_value=float(lambda_e),
                )
            )

        l_m = p.B * 1e-3
        d_out = p.D
        d_in = p.D - 2 * p.t_pps
        c_pps = (2 * np.pi * p.eps_0 * p.eps_r_pps * l_m) / np.log(d_out / d_in) * 1e12

        if total_oil_cap > 0:
            c_system_total = 1 / (1 / total_oil_cap + 1 / c_pps)
        else:
            c_system_total = 0.0

        active_details = [detail for detail in details if detail.load_q_n > 0]
        minimum_film_thickness_um = min(
            (detail.film_thickness_um for detail in active_details),
            default=0.0,
        )
        minimum_outer_film_thickness_um = min(
            (detail.outer_film_thickness_um for detail in active_details),
            default=0.0,
        )
        minimum_lambda = min(
            (detail.lambda_value for detail in active_details),
            default=0.0,
        )
        minimum_outer_lambda = min(
            (detail.outer_lambda_value for detail in active_details),
            default=0.0,
        )

        return CalculationResult(
            oil_capacitance_pf=float(total_oil_cap),
            pps_capacitance_pf=float(c_pps),
            system_capacitance_pf=float(c_system_total),
            ehl_friction_torque_nmm=float(total_ehl_torque_nm * 1000),
            ehl_friction_torque_nm=float(total_ehl_torque_nm),
            radial_displacement_mm=float(dr_mm),
            axial_displacement_mm=float(da_mm),
            operating_kinematic_viscosity_cst=float(operating_kinematic_viscosity_cst),
            reference_kinematic_viscosity_cst=float(reference_kinematic_viscosity),
            kappa=float(kappa),
            minimum_film_thickness_um=float(minimum_film_thickness_um),
            minimum_outer_film_thickness_um=float(minimum_outer_film_thickness_um),
            minimum_lambda=float(minimum_lambda),
            minimum_outer_lambda=float(minimum_outer_lambda),
            solver_converged=ier == 1,
            details=details,
        )


Bearing6208CapacitanceModel = BearingCapacitanceModel
