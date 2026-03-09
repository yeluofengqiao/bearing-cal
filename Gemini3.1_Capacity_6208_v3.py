from bearing_model import Bearing6208CapacitanceModel

# ==========================================
# 执行模拟计算
# ==========================================
if __name__ == "__main__":
    bearing_model = Bearing6208CapacitanceModel()
    result = bearing_model.calculate(fr=3000, fa=1500, speed_rpm=3000)

    print("\n--- 6208 轴承机电联合仿真求解器 (截断爬坡随动版) ---")
    if result.solver_converged:
        print(
            f"求解收敛: 径向位移 = {result.radial_displacement_mm*1000:.1f} um, "
            f"轴向位移 = {result.axial_displacement_mm*1000:.1f} um"
        )
    else:
        print("求解异常: 请检查载荷输入是否过于离谱")

    print(f"系统最终等效电容: C_sys_total = {result.system_capacitance_pf:.2f} pF\n")
    print(f"EHL 油膜摩擦力矩: M_EHL = {result.ehl_friction_torque_nmm:.3f} N·mm ({result.ehl_friction_torque_nm:.6f} N·m)\n")

    print(f"{'角度(°)':<8} {'载荷 Q(N)':<10} {'接触角(°)':<10} {'最大应力(MPa)':<14} {'椭圆截断率':<18} {'内/外膜厚(um)':<20} {'电容(pF)':<10} {'单球力矩(N·mm)':<16}")
    print("-" * 122)
    for row in result.details:
        if row.load_q_n > 0:
            t_ratio = row.truncation_ratio_pct
            alpha_deg = row.contact_angle_deg

            if t_ratio == 0.0:
                trunc_str = "0.0% (安全)"
            elif t_ratio <= 15.0:
                trunc_str = f"{t_ratio:.1f}% (允许)"
            else:
                trunc_str = f"{t_ratio:.1f}% (NG/超标!)"

            print(
                f"{row.angle_deg:<8.0f} {row.load_q_n:<10.1f} {alpha_deg:<10.1f} "
                f"{row.max_stress_mpa:<14.1f} {trunc_str:<18} "
                f"{f'{row.film_thickness_um:.3f}/{row.outer_film_thickness_um:.3f}':<20} "
                f"{row.capacitance_pf:<10.2f} {row.ehl_friction_torque_nmm:<16.3f}"
            )
        else:
            print(
                f"{row.angle_deg:<8.0f} {'---':<10} {'---':<10} {'---':<14} "
                f"{'---':<18} {'---':<20} {'0.00':<10} {'---':<16}"
            )
