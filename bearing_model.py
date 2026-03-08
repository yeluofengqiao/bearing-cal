from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import fsolve
from scipy.special import ellipe, ellipk


@dataclass
class BallDetail:
    angle_deg: float
    load_q_n: float
    max_stress_mpa: float
    truncation_ratio_pct: float
    film_thickness_um: float
    capacitance_pf: float
    contact_angle_deg: float

    def to_dict(self):
        return asdict(self)


@dataclass
class CalculationResult:
    oil_capacitance_pf: float
    pps_capacitance_pf: float
    system_capacitance_pf: float
    radial_displacement_mm: float
    axial_displacement_mm: float
    solver_converged: bool
    details: list[BallDetail]


class Bearing6208CapacitanceModel:
    def __init__(self):
        # 1. 轴承几何参数 (6208)
        self.d = 40.0
        self.D = 80.0
        self.B = 18.0
        self.Dw = 11.906
        self.Dm = 60.0
        self.Z = 9
        self.fi = 0.505
        self.fe = 0.525
        self.Pd = 0.010
        self.L = self.Dw * (self.fi + self.fe - 1)

        # 沟道深度参数 (假设约为钢球直径的 20%)
        self.H_i = 0.20 * self.Dw
        self.H_e = 0.20 * self.Dw

        # 2. 材料力学属性
        self.E = 2.06e5
        self.nu = 0.3
        self.E_prime = self.E / (1 - self.nu**2)

        # 3. 润滑油与电气参数 (70 degC)
        self.eta0 = 0.015
        self.alpha = 1.5e-8
        self.eps_r = 2.1
        self.eps_0 = 8.854e-12

        # 4. PPS+50%GF 包塑层参数
        self.t_pps = 2.0
        self.eps_r_pps = 4.2

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
        rho11 = rho12 = 2 / self.Dw
        if is_inner:
            rho21 = -1 / (self.fi * self.Dw)
            rho22 = -2 / (self.Dm - self.Dw)
        else:
            rho21 = -1 / (self.fe * self.Dw)
            rho22 = 2 / (self.Dm + self.Dw)

        sum_rho = rho11 + rho12 + rho21 + rho22
        diff_rho = (rho11 - rho12) + (rho21 - rho22)
        cos_tau = abs(diff_rho) / sum_rho

        k_el, e_el, k_hd = self._solve_elliptical_param(cos_tau)

        q_test = 1.0
        term_common_1n = (3 * q_test) / (2 * sum_rho * self.E_prime)
        a_star = (2 * (k_hd**2) * e_el / np.pi) ** (1 / 3)
        delta_star = (2 * k_el) / (np.pi * a_star)

        delta_1n = delta_star * (sum_rho / 2) * (term_common_1n ** (2 / 3))
        k_calc = 1.0 / (delta_1n**1.5)
        rx_mm = 1.0 / (rho12 + rho22)

        return k_calc, k_hd, sum_rho, e_el, rx_mm

    def _get_hertz_params(self, q, sum_rho, k_ratio, e_val):
        if q <= 1e-5:
            return 0.0, 0.0, 0.0, 0.0

        term_common = (3 * q) / (2 * sum_rho * self.E_prime)
        a_star = (2 * (k_ratio**2) * e_val / np.pi) ** (1 / 3)
        b_star = (2 * e_val / (np.pi * k_ratio)) ** (1 / 3)

        a = a_star * (term_common ** (1 / 3))
        b = b_star * (term_common ** (1 / 3))
        area = np.pi * a * b
        p_max = (1.5 * q) / area

        return area, a, b, p_max

    def calculate(self, fr, fa, speed_rpm):
        ki, ki_hd, sum_rho_i, e_val_i, rx_i_mm = self.get_contact_stiffness(
            is_inner=True
        )
        ke, ke_hd, sum_rho_e, e_val_e, rx_e_mm = self.get_contact_stiffness(
            is_inner=False
        )

        k_tot = 1 / (((1 / ki) ** (2 / 3) + (1 / ke) ** (2 / 3)) ** 1.5)
        angles = np.linspace(0, 2 * np.pi, self.Z, endpoint=False)

        def equilibrium_equations(vars_um):
            dr = vars_um[0] * 1e-3
            da = vars_um[1] * 1e-3
            fx = 0.0
            fz = 0.0
            for psi in angles:
                term_r = self.L + dr * np.cos(psi)
                term_a = da
                l_new = np.sqrt(term_r**2 + term_a**2)
                delta = l_new - self.L - (self.Pd / 2)
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
        details = []
        u_vel_i = (
            (np.pi * speed_rpm * self.Dm / 120) * (1 - (self.Dw / self.Dm) ** 2) / 1000
        )
        u_vel_e = (
            (np.pi * speed_rpm * self.Dm / 120) * (1 + (self.Dw / self.Dm) ** 2) / 1000
        )

        r_inner = self.fi * self.Dw
        theta_edge_i = np.arccos(1.0 - self.H_i / r_inner)

        for psi in angles:
            term_r = self.L + dr_mm * np.cos(psi)
            term_a = da_mm
            l_new = np.sqrt(term_r**2 + term_a**2)
            delta = l_new - self.L - (self.Pd / 2)

            if delta <= 0:
                details.append(
                    BallDetail(
                        angle_deg=float(np.degrees(psi)),
                        load_q_n=0.0,
                        max_stress_mpa=0.0,
                        truncation_ratio_pct=0.0,
                        film_thickness_um=0.0,
                        capacitance_pf=0.0,
                        contact_angle_deg=0.0,
                    )
                )
                continue

            q = k_tot * delta**1.5
            alpha_contact = np.arcsin(term_a / l_new)
            g_param = self.alpha * (self.E_prime * 1e6)

            rx_i = rx_i_mm / 1000
            u_i = (self.eta0 * u_vel_i) / (self.E_prime * 1e6 * rx_i)
            w_i = q / ((self.E_prime * 1e6) * rx_i**2)
            k_effect_i = 1 - 0.61 * np.exp(-0.73 * ki_hd)
            hc_i = 2.69 * (u_i**0.67) * (g_param**0.53) * (w_i**-0.067) * k_effect_i
            h_i = hc_i * rx_i * 1000

            area_i, a_i, _, pmax_i = self._get_hertz_params(q, sum_rho_i, ki_hd, e_val_i)
            c_in = 0.0
            if h_i > 0:
                c_in = (self.eps_0 * self.eps_r * area_i * 1e-6) / (h_i * 1e-3) * 1e12

            s_avail_i = r_inner * (theta_edge_i - alpha_contact)
            if a_i > s_avail_i:
                trunc_ratio_i = ((a_i - s_avail_i) / (2 * a_i)) * 100.0
            else:
                trunc_ratio_i = 0.0

            rx_e = rx_e_mm / 1000
            u_e = (self.eta0 * u_vel_e) / (self.E_prime * 1e6 * rx_e)
            w_e = q / ((self.E_prime * 1e6) * rx_e**2)
            k_effect_e = 1 - 0.61 * np.exp(-0.73 * ke_hd)
            hc_e = 2.69 * (u_e**0.67) * (g_param**0.53) * (w_e**-0.067) * k_effect_e
            h_e = hc_e * rx_e * 1000

            area_e, _, _, _ = self._get_hertz_params(q, sum_rho_e, ke_hd, e_val_e)
            c_out = 0.0
            if h_e > 0:
                c_out = (self.eps_0 * self.eps_r * area_e * 1e-6) / (h_e * 1e-3) * 1e12

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
                    film_thickness_um=float(h_i * 1000),
                    capacitance_pf=float(c_ball),
                    contact_angle_deg=float(np.degrees(alpha_contact)),
                )
            )

        l_m = self.B * 1e-3
        d_out = self.D
        d_in = self.D - 2 * self.t_pps
        c_pps = (
            (2 * np.pi * self.eps_0 * self.eps_r_pps * l_m) / np.log(d_out / d_in) * 1e12
        )

        if total_oil_cap > 0:
            c_system_total = 1 / (1 / total_oil_cap + 1 / c_pps)
        else:
            c_system_total = 0.0

        return CalculationResult(
            oil_capacitance_pf=float(total_oil_cap),
            pps_capacitance_pf=float(c_pps),
            system_capacitance_pf=float(c_system_total),
            radial_displacement_mm=float(dr_mm),
            axial_displacement_mm=float(da_mm),
            solver_converged=ier == 1,
            details=details,
        )
