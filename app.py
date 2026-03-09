import csv
import io
import os

from flask import Flask, Response, render_template, request

from bearing_model import (
    BearingCapacitanceModel,
    BearingParameters,
    astm_d341_kinematic_viscosity_cst,
    dynamic_viscosity_from_kinematic_cst,
)


app = Flask(__name__)


INPUT_GROUPS = [
    {
        "title": "工况输入",
        "description": "这三项是运行工况，决定载荷和转速。",
        "fields": [
            {
                "name": "fr",
                "label": "径向载荷 Fr",
                "unit": "N",
                "type": "float",
                "step": "100",
                "min": "0",
                "default": 3000.0,
                "help": "轴承承受的径向外载荷，决定受载区钢球分布。",
            },
            {
                "name": "fa",
                "label": "轴向载荷 Fa",
                "unit": "N",
                "type": "float",
                "step": "100",
                "min": "0",
                "default": 1500.0,
                "help": "轴承承受的轴向外载荷，会直接影响接触角与爬坡程度。",
            },
            {
                "name": "speed_rpm",
                "label": "转速",
                "unit": "rpm",
                "type": "float",
                "step": "100",
                "min": "0",
                "default": 3000.0,
                "help": "轴承转速，主要影响滚动速度与油膜厚度。",
            },
        ],
    },
    {
        "title": "轴承几何",
        "description": "这部分决定接触刚度、接触角和包塑层电容。",
        "fields": [
            {"name": "d", "label": "内径 d", "unit": "mm", "type": "float", "step": "0.1", "min": "0.001", "help": "轴承内圈名义内径，当前主要用于几何约束与参数记录。"},
            {"name": "D", "label": "外径 D", "unit": "mm", "type": "float", "step": "0.1", "min": "0.001", "help": "轴承外圈名义外径，直接参与 PPS 包塑层电容计算。"},
            {"name": "B", "label": "宽度 B", "unit": "mm", "type": "float", "step": "0.1", "min": "0.001", "help": "轴承宽度，直接参与 PPS 包塑层轴向长度计算。"},
            {"name": "Dw", "label": "钢球直径 Dw", "unit": "mm", "type": "float", "step": "0.001", "min": "0.001", "help": "滚动体钢球直径，是接触刚度、赫兹接触和油膜计算的核心输入。"},
            {"name": "Dm", "label": "节圆直径 Dm", "unit": "mm", "type": "float", "step": "0.1", "min": "0.001", "help": "钢球中心轨迹所在的节圆直径，影响接触几何和滚动速度。"},
            {"name": "Z", "label": "钢球数 Z", "unit": "个", "type": "int", "step": "1", "min": "1", "help": "轴承内实际参与分布的钢球数量。"},
            {"name": "fi", "label": "内圈沟道曲率系数 fi", "unit": "-", "type": "float", "step": "0.001", "min": "0.001", "help": "内圈沟道曲率半径与钢球直径的比值系数，影响接触曲率与接触刚度。"},
            {"name": "fe", "label": "外圈沟道曲率系数 fe", "unit": "-", "type": "float", "step": "0.001", "min": "0.001", "help": "外圈沟道曲率半径与钢球直径的比值系数，影响外圈接触曲率。"},
            {"name": "Pd", "label": "直径游隙 Pd", "unit": "mm", "type": "float", "step": "0.001", "min": "0", "help": "轴承直径游隙，决定钢球何时开始进入受载接触。"},
            {"name": "H_i", "label": "内圈沟道深度 H_i", "unit": "mm", "type": "float", "step": "0.001", "min": "0.001", "help": "内圈沟道的几何深度，用于判断接触椭圆是否发生截断。"},
        ],
    },
    {
        "title": "材料与润滑",
        "description": "这部分决定赫兹接触、油膜厚度、λ、κ 和电容介电特性。默认值已经填好，不改也可以直接计算。",
        "fields": [
            {"name": "E", "label": "杨氏模量 E", "unit": "MPa", "type": "float", "step": "1000", "min": "0.001", "help": "材料刚度参数，越大表示接触越硬。钢常见默认值约 2.06e5 MPa。"},
            {"name": "nu", "label": "泊松比 nu", "unit": "-", "type": "float", "step": "0.01", "min": "0.001", "max": "0.499", "help": "材料横向变形系数，钢常取 0.3 左右。"},
            {"name": "nu_40_cst", "label": "运动黏度 ν40", "unit": "cSt", "type": "float", "step": "0.001", "min": "0", "help": "油品 40℃ 运动黏度。若 ν40 和 ν100 都大于 0，则程序优先按 ASTM D341 推算当前黏度。"},
            {"name": "nu_100_cst", "label": "运动黏度 ν100", "unit": "cSt", "type": "float", "step": "0.001", "min": "0", "help": "油品 100℃ 运动黏度。需与 ν40 成对输入。"},
            {"name": "oil_temperature_c", "label": "油温", "unit": "℃", "type": "float", "step": "1", "min": "0", "help": "用于把 ν40 / ν100 换算到当前工况黏度，并参与 κ 计算。"},
            {"name": "oil_density_kg_m3", "label": "油品密度", "unit": "kg/m³", "type": "float", "step": "1", "min": "0.001", "help": "用于把当前运动黏度换算为动力黏度 eta0；没有实测值时可先用 850。"},
            {"name": "eta0", "label": "动力黏度 eta0", "unit": "Pa·s", "type": "float", "step": "0.0001", "min": "0.000001", "help": "如果不想输入 ν40 / ν100，可直接输入当前温度下的动力黏度。只有当 ν40 和 ν100 都为 0 时，程序才使用该值。"},
            {"name": "composite_roughness_um", "label": "综合粗糙度 σ", "unit": "um", "type": "float", "step": "0.001", "min": "0.001", "help": "λ = h / σ。若没有实测值，可先用 0.052 um 做工程估算。"},
            {"name": "alpha", "label": "压黏系数 alpha", "unit": "1/Pa", "type": "float", "step": "0.000000001", "min": "0.000000000001", "help": "压力升高时润滑油黏度增加的敏感系数。"},
            {"name": "eps_r", "label": "油膜相对介电常数 eps_r", "unit": "-", "type": "float", "step": "0.1", "min": "0.001", "help": "接触油膜的相对介电常数，直接影响油膜电容。"},
            {"name": "t_pps", "label": "PPS 厚度 t_pps", "unit": "mm", "type": "float", "step": "0.1", "min": "0.001", "help": "包塑 PPS 绝缘层厚度，越厚通常电容越小。"},
            {"name": "eps_r_pps", "label": "PPS 相对介电常数 eps_r_pps", "unit": "-", "type": "float", "step": "0.1", "min": "0.001", "help": "PPS 包塑层材料的相对介电常数，用于包塑层电容计算。"},
            {"name": "slip_ratio_inner", "label": "内圈滑滚比 slip_ratio_inner", "unit": "-", "type": "float", "step": "0.001", "min": "0", "help": "EHL 剪切力矩中，内圈接触相对滑动速度近似为内圈卷吸速度乘以该比例。"},
            {"name": "slip_ratio_outer", "label": "外圈滑滚比 slip_ratio_outer", "unit": "-", "type": "float", "step": "0.001", "min": "0", "help": "EHL 剪切力矩中，外圈接触相对滑动速度近似为外圈卷吸速度乘以该比例。"},
            {"name": "shear_limit_factor", "label": "极限剪应力系数 shear_limit_factor", "unit": "-", "type": "float", "step": "0.001", "min": "0.001", "help": "油膜极限牵引剪应力近似取平均接触压强乘以该系数。"},
            {"name": "max_shear_stress_mpa", "label": "最大剪应力上限", "unit": "MPa", "type": "float", "step": "1", "min": "0.1", "help": "用于抑制 Barus 压黏模型在高压下的过大剪应力。"},
        ],
    },
]


def build_default_inputs():
    params = BearingParameters()
    defaults = params.to_dict()
    defaults.update(
        {
            "fr": 3000.0,
            "fa": 1500.0,
            "speed_rpm": 3000.0,
            "nu_40_cst": 0.0,
            "nu_100_cst": 0.0,
            "oil_temperature_c": 90.0,
        }
    )
    return defaults


DEFAULT_INPUTS = build_default_inputs()


def parameter_notes():
    return [
        "如果输入 ν40 和 ν100，程序会先按 ASTM D341 计算当前温度下的运动黏度，再结合密度换算为动力黏度 eta0；否则直接使用手动输入的 eta0。",
        "κ 按参考黏度法计算：κ = ν / ν1，其中 ν1 由节圆直径 Dm 和转速 n 估算；若你要和 SKF/NSK 手册对表，请确保 Dm 与目录值一致。",
        "λ 按 λ = h / σ 计算，h 使用当前 EHL 膜厚模型，σ 为综合粗糙度；如果没有粗糙度实测值，可先用 0.052 um 做对比估算。",
        "EHL 摩擦力矩按油膜剪切求解：先算膜厚，再用滑滚比估算相对滑动速度，并通过极限剪应力系数与最大剪应力上限约束牵引应力。",
        "内径 d、外径 D、宽度 B 目前主要用于几何描述和 PPS 层电容计算，其中 D 与 B 已直接参与计算。",
    ]


def iter_fields():
    for group in INPUT_GROUPS:
        for field in group["fields"]:
            yield field


FIELD_MAP = {field["name"]: field for field in iter_fields()}


def detail_rows(result):
    rows = []
    for detail in result.details:
        if detail.truncation_ratio_pct == 0.0:
            truncation_status = "0.0% (安全)"
        elif detail.truncation_ratio_pct <= 15.0:
            truncation_status = f"{detail.truncation_ratio_pct:.1f}% (允许)"
        else:
            truncation_status = f"{detail.truncation_ratio_pct:.1f}% (NG/超标)"

        rows.append(
            {
                "angle_deg": detail.angle_deg,
                "load_q_n": detail.load_q_n,
                "max_stress_mpa": detail.max_stress_mpa,
                "truncation_ratio_pct": detail.truncation_ratio_pct,
                "truncation_status": truncation_status,
                "film_thickness_um": detail.film_thickness_um,
                "outer_film_thickness_um": detail.outer_film_thickness_um,
                "capacitance_pf": detail.capacitance_pf,
                "contact_angle_deg": detail.contact_angle_deg,
                "ehl_friction_force_n": detail.ehl_friction_force_n,
                "ehl_friction_torque_nmm": detail.ehl_friction_torque_nmm,
                "traction_coeff_inner": detail.traction_coeff_inner,
                "traction_coeff_outer": detail.traction_coeff_outer,
                "lambda_value": detail.lambda_value,
                "outer_lambda_value": detail.outer_lambda_value,
                "is_active": detail.load_q_n > 0,
            }
        )
    return rows


def resolve_viscosity(inputs):
    density = inputs["oil_density_kg_m3"]
    nu_40_cst = inputs["nu_40_cst"]
    nu_100_cst = inputs["nu_100_cst"]

    if (nu_40_cst > 0) != (nu_100_cst > 0):
        raise ValueError("ν40 和 ν100 需要成对输入；要么都填，要么都留为 0。")

    if nu_40_cst > 0 and nu_100_cst > 0:
        operating_kinematic_viscosity_cst = astm_d341_kinematic_viscosity_cst(
            nu_40_cst,
            nu_100_cst,
            inputs["oil_temperature_c"],
        )
        eta0 = dynamic_viscosity_from_kinematic_cst(
            operating_kinematic_viscosity_cst,
            density,
        )
        viscosity_source = "ASTM D341"
    else:
        eta0 = inputs["eta0"]
        operating_kinematic_viscosity_cst = eta0 / density * 1e6
        viscosity_source = "直接输入 eta0"

    return eta0, operating_kinematic_viscosity_cst, viscosity_source


def parse_inputs(source):
    values = {}
    for name, field in FIELD_MAP.items():
        raw_value = str(source.get(name, DEFAULT_INPUTS[name])).strip()
        if raw_value == "":
            raise ValueError(f"{field['label']} 不能为空。")

        try:
            if field["type"] == "int":
                values[name] = int(raw_value)
            else:
                values[name] = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"{field['label']} 需要输入有效数字。") from exc
    return values


def build_parameters(inputs):
    eta0, _, _ = resolve_viscosity(inputs)
    return BearingParameters(
        d=inputs["d"],
        D=inputs["D"],
        B=inputs["B"],
        Dw=inputs["Dw"],
        Dm=inputs["Dm"],
        Z=inputs["Z"],
        fi=inputs["fi"],
        fe=inputs["fe"],
        Pd=inputs["Pd"],
        H_i=inputs["H_i"],
        E=inputs["E"],
        nu=inputs["nu"],
        eta0=eta0,
        oil_density_kg_m3=inputs["oil_density_kg_m3"],
        composite_roughness_um=inputs["composite_roughness_um"],
        alpha=inputs["alpha"],
        eps_r=inputs["eps_r"],
        t_pps=inputs["t_pps"],
        eps_r_pps=inputs["eps_r_pps"],
        slip_ratio_inner=inputs["slip_ratio_inner"],
        slip_ratio_outer=inputs["slip_ratio_outer"],
        shear_limit_factor=inputs["shear_limit_factor"],
        max_shear_stress_mpa=inputs["max_shear_stress_mpa"],
    )


def build_summary(result, rows):
    active_rows = [row for row in rows if row["is_active"]]
    peak_load = max((row["load_q_n"] for row in active_rows), default=0.0)
    peak_capacitance = max((row["capacitance_pf"] for row in active_rows), default=0.0)
    peak_contact_angle = max((row["contact_angle_deg"] for row in active_rows), default=0.0)
    peak_ball_torque = max((row["ehl_friction_torque_nmm"] for row in active_rows), default=0.0)
    return {
        "active_ball_count": len(active_rows),
        "peak_load_q_n": peak_load,
        "peak_ball_capacitance_pf": peak_capacitance,
        "peak_contact_angle_deg": peak_contact_angle,
        "peak_ball_torque_nmm": peak_ball_torque,
        "operating_kinematic_viscosity_cst": result.operating_kinematic_viscosity_cst,
        "reference_kinematic_viscosity_cst": result.reference_kinematic_viscosity_cst,
        "kappa": result.kappa,
        "minimum_film_thickness_um": result.minimum_film_thickness_um,
        "minimum_outer_film_thickness_um": result.minimum_outer_film_thickness_um,
        "minimum_lambda": result.minimum_lambda,
        "minimum_outer_lambda": result.minimum_outer_lambda,
        "total_ehl_torque_nmm": result.ehl_friction_torque_nmm,
        "total_ehl_torque_nm": result.ehl_friction_torque_nm,
        "solver_status": "求解收敛" if result.solver_converged else "求解未收敛",
    }


def run_calculation(inputs):
    model = BearingCapacitanceModel(build_parameters(inputs))
    result = model.calculate(
        fr=inputs["fr"],
        fa=inputs["fa"],
        speed_rpm=inputs["speed_rpm"],
    )
    rows = detail_rows(result)
    summary = build_summary(result, rows)
    return result, rows, summary


def build_csv(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "angle_deg",
            "load_q_n",
            "contact_angle_deg",
            "max_stress_mpa",
            "truncation_ratio_pct",
            "film_thickness_inner_um",
            "film_thickness_outer_um",
            "lambda_inner",
            "lambda_outer",
            "capacitance_pf",
            "ehl_friction_force_n",
            "ehl_friction_torque_nmm",
            "traction_coeff_inner",
            "traction_coeff_outer",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                f"{row['angle_deg']:.0f}",
                f"{row['load_q_n']:.4f}",
                f"{row['contact_angle_deg']:.4f}",
                f"{row['max_stress_mpa']:.4f}",
                f"{row['truncation_ratio_pct']:.4f}",
                f"{row['film_thickness_um']:.6f}",
                f"{row['outer_film_thickness_um']:.6f}",
                f"{row['lambda_value']:.6f}",
                f"{row['outer_lambda_value']:.6f}",
                f"{row['capacitance_pf']:.6f}",
                f"{row['ehl_friction_force_n']:.6f}",
                f"{row['ehl_friction_torque_nmm']:.6f}",
                f"{row['traction_coeff_inner']:.6f}",
                f"{row['traction_coeff_outer']:.6f}",
            ]
        )
    return buffer.getvalue()


@app.route("/", methods=["GET", "POST"])
def index():
    inputs = DEFAULT_INPUTS.copy()
    result = None
    rows = []
    summary = None
    error_message = None

    if request.method == "POST":
        try:
            inputs = parse_inputs(request.form)
            result, rows, summary = run_calculation(inputs)
        except ValueError as exc:
            error_message = str(exc)

    return render_template(
        "index.html",
        input_groups=INPUT_GROUPS,
        inputs=inputs,
        result=result,
        rows=rows,
        summary=summary,
        error_message=error_message,
        parameter_notes=parameter_notes(),
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200


@app.get("/download.csv")
def download_csv():
    try:
        inputs = parse_inputs(request.args)
        result, rows, _ = run_calculation(inputs)
    except ValueError as exc:
        return Response(str(exc), status=400, mimetype="text/plain")

    if not result.solver_converged:
        return Response("求解器未收敛，未生成 CSV。", status=400, mimetype="text/plain")

    csv_text = build_csv(rows)
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=bearing_results.csv"
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
