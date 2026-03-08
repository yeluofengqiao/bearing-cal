import pandas as pd
import streamlit as st

from bearing_model import Bearing6208CapacitanceModel


def build_detail_frame(result):
    rows = [detail.to_dict() for detail in result.details]
    frame = pd.DataFrame(rows)
    return frame.rename(
        columns={
            "angle_deg": "角度 (deg)",
            "load_q_n": "载荷 Q (N)",
            "max_stress_mpa": "最大应力 (MPa)",
            "truncation_ratio_pct": "椭圆截断率 (%)",
            "film_thickness_um": "油膜厚度 (um)",
            "capacitance_pf": "单球电容 (pF)",
            "contact_angle_deg": "接触角 (deg)",
        }
    )


st.set_page_config(
    page_title="6208 轴承电容计算器",
    layout="centered",
)

st.title("6208 轴承机电联合仿真计算器")
st.caption("基于现有 6208 轴承电容模型封装，适合手机浏览器直接访问。")

with st.sidebar:
    st.subheader("说明")
    st.write("输入载荷和转速后，页面会计算总电容、位移，以及每颗钢球的载荷明细。")
    st.write("默认模型参数来自你的原始脚本，后续可以继续扩展为更多轴承型号。")

with st.form("bearing_form"):
    col1, col2 = st.columns(2)
    with col1:
        fr = st.number_input("径向载荷 Fr (N)", min_value=0.0, value=3000.0, step=100.0)
        fa = st.number_input("轴向载荷 Fa (N)", min_value=0.0, value=1500.0, step=100.0)
    with col2:
        speed_rpm = st.number_input(
            "转速 (rpm)",
            min_value=0.0,
            value=3000.0,
            step=100.0,
        )
    submitted = st.form_submit_button("开始计算", use_container_width=True)

if submitted:
    model = Bearing6208CapacitanceModel()
    result = model.calculate(fr=fr, fa=fa, speed_rpm=speed_rpm)
    detail_df = build_detail_frame(result)

    if result.solver_converged:
        st.success("求解收敛。")
    else:
        st.warning("求解器未正常收敛，结果可供参考，但建议检查输入工况。")

    metric_col1, metric_col2 = st.columns(2)
    with metric_col1:
        st.metric("系统最终等效电容", f"{result.system_capacitance_pf:.2f} pF")
        st.metric("油膜总电容", f"{result.oil_capacitance_pf:.2f} pF")
    with metric_col2:
        st.metric("PPS 层电容", f"{result.pps_capacitance_pf:.2f} pF")
        st.metric("径向/轴向位移", f"{result.radial_displacement_mm*1000:.1f} / {result.axial_displacement_mm*1000:.1f} um")

    st.subheader("角度分布")
    chart_df = detail_df.set_index("角度 (deg)")[
        ["载荷 Q (N)", "单球电容 (pF)", "接触角 (deg)"]
    ]
    st.line_chart(chart_df, height=280)

    st.subheader("钢球明细")
    st.dataframe(
        detail_df.style.format(
            {
                "角度 (deg)": "{:.0f}",
                "载荷 Q (N)": "{:.2f}",
                "最大应力 (MPa)": "{:.2f}",
                "椭圆截断率 (%)": "{:.2f}",
                "油膜厚度 (um)": "{:.4f}",
                "单球电容 (pF)": "{:.4f}",
                "接触角 (deg)": "{:.2f}",
            }
        ),
        use_container_width=True,
        height=380,
    )

    csv_data = detail_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "下载明细 CSV",
        data=csv_data,
        file_name="bearing_6208_results.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
    st.info("填入参数后点击“开始计算”。")
