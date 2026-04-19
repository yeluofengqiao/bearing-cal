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
from tapered_preload_calculator import (
    TaperedPreloadInputs,
    calculate_tapered_preload,
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
            {"name": "shear_limit_factor", "label": "极限剪应力系数 shear_limit_factor", "unit": "-", "type": "float", "step": "0.001", "min": "0.001", "help": "油膜极限牵引剪应力近似取平均接触压强乘以该系数。"},
            {"name": "max_shear_stress_mpa", "label": "最大剪应力上限", "unit": "MPa", "type": "float", "step": "1", "min": "0.1", "help": "用于抑制 Barus 压黏模型在高压下的过大剪应力。"},
        ],
    },
]


TAPERED_PRELOAD_INPUT_GROUPS = [
    {
        "title": "基准与目标",
        "description": "先给定常温零游隙基准垫片，再定义你希望热态保留的最小/目标预紧力。",
        "fields": [
            {
                "name": "zero_endplay_shim_mm",
                "label": "零游隙基准垫片",
                "unit": "mm",
                "type": "float",
                "step": "0.001",
                "min": "0.001",
                "default": 2.500,
                "help": "指常温试装时恰好消除游隙、但尚未形成预紧的基准厚度；推荐先由量测或试装得到该值。",
            },
            {
                "name": "minimum_hot_preload_n",
                "label": "热态最小预紧力",
                "unit": "N",
                "type": "float",
                "step": "10",
                "min": "0",
                "default": 200.0,
                "help": "用于判定热态是否仍能避免留隙；一般这是你不希望低于的底线值。",
            },
            {
                "name": "target_hot_preload_n",
                "label": "热态目标预紧力",
                "unit": "N",
                "type": "float",
                "step": "10",
                "min": "0",
                "default": 1000.0,
                "help": "连续推荐值会按这个目标反推；通常应大于等于热态最小预紧力。",
            },
            {
                "name": "shim_step_mm",
                "label": "垫片分档步距",
                "unit": "mm",
                "type": "float",
                "step": "0.001",
                "min": "0.001",
                "default": 0.020,
                "help": "用于把连续厚度换算成离散厚度点；如果你们的垫片以 0.02 mm 分档，就填 0.02。",
            },
            {
                "name": "preload_direction",
                "label": "预紧方向",
                "type": "select",
                "default": "thinner_increases_preload",
                "options": [
                    {
                        "value": "thinner_increases_preload",
                        "label": "垫片更薄 -> 预紧更大",
                    },
                    {
                        "value": "thicker_increases_preload",
                        "label": "垫片更厚 -> 预紧更大",
                    },
                ],
                "help": "多数端盖垫片结构是“更薄更紧”；如果你们的布置相反，可以改成“更厚更紧”。",
            },
        ],
    },
    {
        "title": "刚性输入",
        "description": "把左右圆锥滚子轴承、座孔支承结构和轴向支承路径视为串联弹簧，用轴向刚度参与求解。",
        "fields": [
            {
                "name": "left_bearing_stiffness_n_per_mm",
                "label": "左轴承轴向刚度",
                "unit": "N/mm",
                "type": "float",
                "step": "1000",
                "min": "0.001",
                "default": 100000.0,
                "help": "建议优先采用轴承目录、试验或供应商给出的预紧区间轴向刚度，而不是简单拍值。",
            },
            {
                "name": "right_bearing_stiffness_n_per_mm",
                "label": "右轴承轴向刚度",
                "unit": "N/mm",
                "type": "float",
                "step": "1000",
                "min": "0.001",
                "default": 100000.0,
                "help": "若左右轴承型号相同，可先填成同一个值；若结构不对称，建议分别输入。",
            },
            {
                "name": "housing_stiffness_n_per_mm",
                "label": "座孔等效刚度",
                "unit": "N/mm",
                "type": "float",
                "step": "1000",
                "min": "0.001",
                "default": 200000.0,
                "help": "这里建议填端盖、箱体、座孔台肩等结构在轴向预紧路径上的等效刚度，可来自 FEA 或台架。",
            },
            {
                "name": "shaft_stiffness_n_per_mm",
                "label": "轴等效刚度",
                "unit": "N/mm",
                "type": "float",
                "step": "1000",
                "min": "0.001",
                "default": 200000.0,
                "help": "这里是轴及其相关支承路径在轴向方向上的等效刚度；与座孔一样，建议优先用结构计算或仿真值。",
            },
        ],
    },
    {
        "title": "热膨胀输入",
        "description": "这里按铝合金座孔有效跨距的热膨胀来估算预紧损失，暂未把轴热膨胀单独叠加进去。",
        "fields": [
            {
                "name": "housing_alpha_per_c",
                "label": "座孔线膨胀系数",
                "unit": "1/℃",
                "type": "float",
                "step": "0.000001",
                "min": "0.0000001",
                "default": 0.000023,
                "help": "铝合金常可先按 23e-6 /℃ 估算；若掌握实测材料牌号数据，建议直接替换。",
            },
            {
                "name": "housing_effective_span_mm",
                "label": "座孔有效跨距",
                "unit": "mm",
                "type": "float",
                "step": "0.1",
                "min": "0.001",
                "default": 60.0,
                "help": "指两个受热后会拉开轴承外圈定位面的有效轴向距离，而不是整个箱体总长。",
            },
            {
                "name": "housing_delta_temp_c",
                "label": "座孔温升",
                "unit": "℃",
                "type": "float",
                "step": "1",
                "default": 80.0,
                "help": "按工作状态相对装配常温的温升输入；如果安装温度就是 20℃，运行时座孔到 100℃，这里填 80。",
            },
        ],
    },
]


def iter_group_fields(groups):
    for group in groups:
        for field in group["fields"]:
            yield field


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
TAPERED_DEFAULT_INPUTS = {
    field["name"]: field["default"]
    for field in iter_group_fields(TAPERED_PRELOAD_INPUT_GROUPS)
}


def parameter_notes():
    return [
        "如果输入 ν40 和 ν100，程序会先按 ASTM D341 计算当前温度下的运动黏度，再结合密度换算为动力黏度 eta0；否则直接使用手动输入的 eta0。",
        "κ 按参考黏度法计算：κ = ν / ν1，其中 ν1 由节圆直径 Dm 和转速 n 估算；若你要和 SKF/NSK 手册对表，请确保 Dm 与目录值一致。",
        "λ 按 λ = h / σ 计算，h 使用当前 EHL 膜厚模型，σ 为综合粗糙度；如果没有粗糙度实测值，可先用 0.052 um 做对比估算。",
        "EHL 摩擦力矩按油膜剪切求解：程序会根据沟道曲率系数 fi/fe、节圆与钢球尺寸比 Dw/Dm，以及每个受载钢球的接触角自动估算内圈和外圈滑滚比。",
        "内径 d、外径 D、宽度 B 目前主要用于几何描述和 PPS 层电容计算，其中 D 与 B 已直接参与计算。",
    ]


def tapered_parameter_notes():
    return [
        "本页采用一维轴向串联刚度模型：左右轴承、座孔结构和轴等效为串联弹簧，适合用于预压垫片的工程初算与点位推荐。",
        "零游隙基准垫片不是名义尺寸，而是你在常温试装时刚好消除游隙的参考厚度；程序在此基础上再叠加热补偿与目标预紧位移。",
        "座孔热膨胀按 ΔL = alpha × L × ΔT 处理；当前版本只显式考虑铝合金座孔拉开导致的预紧损失，未单独叠加轴热膨胀。",
        "轴承、座孔和轴刚度建议优先采用目录曲线、有限元或台架辨识结果；如果刚度取值偏差较大，推荐的垫片点也会相应偏移。",
        "连续推荐值用于看理论厚度，离散推荐点按你给定的垫片分档步距生成；如果你们的垫片库是不等差系列，可再按输出结果手动对照。",
    ]


FIELD_MAP = {field["name"]: field for field in iter_group_fields(INPUT_GROUPS)}
TAPERED_FIELD_MAP = {
    field["name"]: field for field in iter_group_fields(TAPERED_PRELOAD_INPUT_GROUPS)
}


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
                "estimated_slip_ratio_inner": detail.estimated_slip_ratio_inner,
                "estimated_slip_ratio_outer": detail.estimated_slip_ratio_outer,
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


def parse_tapered_inputs(source):
    values = {}
    for name, field in TAPERED_FIELD_MAP.items():
        raw_value = source.get(name, TAPERED_DEFAULT_INPUTS[name])
        if field["type"] == "select":
            raw_value = str(raw_value).strip()
            allowed_values = {option["value"] for option in field["options"]}
            if raw_value not in allowed_values:
                raise ValueError(f"{field['label']} 取值无效。")
            values[name] = raw_value
            continue

        raw_value = str(raw_value).strip()
        if raw_value == "":
            raise ValueError(f"{field['label']} 不能为空。")

        try:
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
        shear_limit_factor=inputs["shear_limit_factor"],
        max_shear_stress_mpa=inputs["max_shear_stress_mpa"],
    )


def build_tapered_preload_inputs(values):
    return TaperedPreloadInputs(
        zero_endplay_shim_mm=values["zero_endplay_shim_mm"],
        minimum_hot_preload_n=values["minimum_hot_preload_n"],
        target_hot_preload_n=values["target_hot_preload_n"],
        left_bearing_stiffness_n_per_mm=values["left_bearing_stiffness_n_per_mm"],
        right_bearing_stiffness_n_per_mm=values["right_bearing_stiffness_n_per_mm"],
        housing_stiffness_n_per_mm=values["housing_stiffness_n_per_mm"],
        shaft_stiffness_n_per_mm=values["shaft_stiffness_n_per_mm"],
        housing_alpha_per_c=values["housing_alpha_per_c"],
        housing_effective_span_mm=values["housing_effective_span_mm"],
        housing_delta_temp_c=values["housing_delta_temp_c"],
        shim_step_mm=values["shim_step_mm"],
        preload_direction=values["preload_direction"],
    )


def lambda_regime_label(lambda_value):
    if lambda_value < 1.0:
        return "边界润滑风险"
    if lambda_value < 2.0:
        return "混合润滑偏弱"
    if lambda_value < 3.0:
        return "混合润滑可用"
    return "全膜润滑较稳妥"


def kappa_regime_label(kappa):
    if kappa < 0.6:
        return "黏度储备明显不足"
    if kappa < 1.0:
        return "黏度储备偏低"
    if kappa <= 4.0:
        return "黏度储备基本合适"
    return "黏度储备偏高"


def build_consistency_alerts(
    kappa,
    minimum_lambda,
    limit_location,
):
    alerts = []

    if minimum_lambda < 1.0 and kappa >= 2.0:
        alerts.append(
            {
                "level": "danger",
                "level_label": "反向信号",
                "title": "λ 偏低但 κ 偏高",
                "body": (
                    f"{limit_location}最小 λ 只有 {minimum_lambda:.2f}，但 κ 已达到 {kappa:.2f}。"
                    "这说明不能只凭油品黏度储备判断润滑安全，限制项更可能来自表面粗糙度、局部接触载荷、"
                    "对中偏差或最不利位置的速度条件。"
                ),
                "actions": [
                    "不要只看 κ 下结论，先以最不利位置 λ 作为风险判断主线。",
                    "优先检查综合粗糙度 σ 是否偏大，以及局部载荷、对中和接触位置是否导致膜厚被压缩。",
                    "复核温度、黏度、密度、转速和节圆直径 Dm 的输入是否一致，必要时对照试验或目录数据。",
                ],
            }
        )
    elif minimum_lambda < 2.0 and kappa >= 4.0:
        alerts.append(
            {
                "level": "warn",
                "level_label": "结果分化",
                "title": "κ 很高，但 λ 仍停留在混合润滑区",
                "body": (
                    f"{limit_location}最小 λ 为 {minimum_lambda:.2f}，仍未进入更稳妥区间，而 κ 已达到 {kappa:.2f}。"
                    "这通常说明继续单纯加黏度的收益开始变弱，下一步更该排查粗糙度和局部接触条件。"
                ),
                "actions": [
                    "把优化重点从单纯提黏度，转向粗糙度、载荷分配和对中状态。",
                    "如果 κ 已明显偏高，再继续提黏度前先确认是否会带来搅油损失和温升副作用。",
                ],
            }
        )

    if minimum_lambda >= 3.0 and kappa < 1.0:
        alerts.append(
            {
                "level": "warn",
                "level_label": "敏感工况",
                "title": "λ 尚可，但 κ 偏低",
                "body": (
                    f"{limit_location}最小 λ 已有 {minimum_lambda:.2f}，但 κ 只有 {kappa:.2f}。"
                    "这表示当前工况下膜厚还能维持，但对油温上升、油品老化和转速波动的敏感性会更高。"
                ),
                "actions": [
                    "建议给黏度留出一点额外余量，避免现场温升或老化后 κ 进一步下滑。",
                    "重点关注稳定油温和持续工况，不要把当前一次性算例直接当成长期裕量。",
                ],
            }
        )

    return alerts


def build_lubrication_recommendation(
    kappa,
    minimum_inner_lambda,
    minimum_outer_lambda,
):
    if minimum_inner_lambda <= minimum_outer_lambda:
        minimum_lambda = minimum_inner_lambda
        limit_location = "内圈"
    else:
        minimum_lambda = minimum_outer_lambda
        limit_location = "外圈"

    lambda_label = lambda_regime_label(minimum_lambda)
    kappa_label = kappa_regime_label(kappa)
    consistency_alerts = build_consistency_alerts(
        kappa,
        minimum_lambda,
        limit_location,
    )

    if minimum_lambda < 1.0 or kappa < 0.6:
        level = "danger"
        level_label = "偏弱"
        headline = "润滑状态偏弱"
    elif minimum_lambda < 2.0 or kappa < 1.0:
        level = "warn"
        level_label = "可优化"
        headline = "润滑状态需要加强"
    elif minimum_lambda >= 2.0 and kappa > 4.0:
        level = "warn"
        level_label = "偏保守"
        headline = "润滑充足，但黏度偏保守"
    else:
        level = "good"
        level_label = "较稳妥"
        headline = "润滑状态较均衡"

    actions = []
    if kappa < 1.0:
        actions.append(
            "优先提高运行黏度：可考虑更高 ν40 / ν100 的油品，或把稳定油温再压低一些，先把 κ 拉回到 1 以上。"
        )
    elif kappa > 4.0:
        actions.append(
            "如果现场更关注效率、发热或搅油损失，可以评估略低一级黏度油品，但前提是最小 λ 不要明显掉出目标区间。"
        )
    else:
        actions.append(
            "当前黏度储备基本合适，油品等级可以先保持不变，优化重点更适合放在温升稳定性和接触表面状态上。"
        )

    if minimum_lambda < 1.0:
        actions.append(
            f"{limit_location}最小 λ 已低于 1，存在混合/边界润滑风险；建议优先检查综合粗糙度 σ、峰值载荷和局部速度，并同步评估提高黏度的空间。"
        )
    elif minimum_lambda < 3.0:
        actions.append(
            f"{limit_location}最小 λ 仍处在混合润滑区；如果目标是更稳妥的寿命或耐久，可以适当提高黏度余量，或把综合粗糙度 σ 再往下压。"
        )
    else:
        actions.append(
            f"{limit_location}最小 λ 已进入较稳妥区间，当前表面分离条件整体较好。"
        )

    if kappa >= 1.0 and minimum_lambda < 1.5:
        actions.append(
            "κ 不算低但 λ 仍偏小，说明限制项不只在油品黏度，更可能来自粗糙度、载荷分配、对中或局部速度。"
        )
    elif minimum_lambda >= 3.0 and kappa < 1.0:
        actions.append(
            "λ 目前还能维持，但 κ 偏低意味着对油温上升和工况波动会更敏感，建议给黏度多留一点余量。"
        )

    summary = (
        f"最不利位置在{limit_location}，最小 λ = {minimum_lambda:.2f}（{lambda_label}）；"
        f"κ = {kappa:.2f}（{kappa_label}）。"
    )
    note = (
        "经验阈值可先按 κ < 1 视为黏度储备偏低，最小 λ < 1 视为边界润滑风险，"
        "1 到 3 视为混合润滑，超过 3 通常更稳妥。"
    )

    return {
        "level": level,
        "level_label": level_label,
        "headline": headline,
        "summary": summary,
        "actions": actions,
        "note": note,
        "alerts": consistency_alerts,
    }


def build_summary(result, rows):
    active_rows = [row for row in rows if row["is_active"]]
    peak_load = max((row["load_q_n"] for row in active_rows), default=0.0)
    peak_capacitance = max((row["capacitance_pf"] for row in active_rows), default=0.0)
    peak_contact_angle = max((row["contact_angle_deg"] for row in active_rows), default=0.0)
    peak_ball_torque = max((row["ehl_friction_torque_nmm"] for row in active_rows), default=0.0)
    peak_inner_slip_ratio = max(
        (row["estimated_slip_ratio_inner"] for row in active_rows),
        default=0.0,
    )
    peak_outer_slip_ratio = max(
        (row["estimated_slip_ratio_outer"] for row in active_rows),
        default=0.0,
    )
    recommendation = build_lubrication_recommendation(
        result.kappa,
        result.minimum_lambda,
        result.minimum_outer_lambda,
    )
    return {
        "active_ball_count": len(active_rows),
        "peak_load_q_n": peak_load,
        "peak_ball_capacitance_pf": peak_capacitance,
        "peak_contact_angle_deg": peak_contact_angle,
        "peak_ball_torque_nmm": peak_ball_torque,
        "peak_inner_slip_ratio": peak_inner_slip_ratio,
        "peak_outer_slip_ratio": peak_outer_slip_ratio,
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
        "recommendation": recommendation,
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
            "estimated_slip_ratio_inner",
            "estimated_slip_ratio_outer",
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
                f"{row['estimated_slip_ratio_inner']:.6f}",
                f"{row['estimated_slip_ratio_outer']:.6f}",
                f"{row['ehl_friction_force_n']:.6f}",
                f"{row['ehl_friction_torque_nmm']:.6f}",
                f"{row['traction_coeff_inner']:.6f}",
                f"{row['traction_coeff_outer']:.6f}",
            ]
        )
    return buffer.getvalue()


def build_tapered_summary(inputs, result):
    selected = result.selected_point
    nominal_adjustment_mm = inputs["zero_endplay_shim_mm"] - result.nominal_shim_mm
    selected_adjustment_mm = inputs["zero_endplay_shim_mm"] - selected.shim_mm

    if nominal_adjustment_mm > 0:
        nominal_action = "减薄"
    elif nominal_adjustment_mm < 0:
        nominal_action = "加厚"
    else:
        nominal_action = "保持不变"

    return {
        "nominal_adjustment_mm": nominal_adjustment_mm,
        "nominal_adjustment_abs_mm": abs(nominal_adjustment_mm),
        "selected_adjustment_mm": selected_adjustment_mm,
        "nominal_action": nominal_action,
        "selected_hot_preload_n": selected.hot_preload_n,
        "selected_hot_clearance_um": selected.hot_clearance_mm * 1000.0,
        "selected_cold_preload_n": selected.cold_preload_n,
        "selected_margin_to_min_hot_preload_n": selected.margin_to_min_hot_preload_n,
        "selected_margin_to_target_hot_preload_n": selected.margin_to_target_hot_preload_n,
    }


def build_tapered_point_rows(inputs, result):
    rows = []
    selected_shim = result.selected_shim_mm

    for point in result.candidate_points:
        if point.hot_clearance_mm > 0:
            status = f"热态留隙 {point.hot_clearance_mm * 1000.0:.1f} um"
        elif point.hot_preload_n < inputs["minimum_hot_preload_n"]:
            status = "低于热态下限"
        elif abs(point.shim_mm - selected_shim) < 1e-9:
            status = "推荐点"
        else:
            status = "可选点"

        rows.append(
            {
                "shim_mm": point.shim_mm,
                "cold_preload_n": point.cold_preload_n,
                "hot_preload_n": point.hot_preload_n,
                "cold_clearance_um": point.cold_clearance_mm * 1000.0,
                "hot_clearance_um": point.hot_clearance_mm * 1000.0,
                "delta_from_nominal_um": point.delta_from_nominal_mm * 1000.0,
                "margin_to_min_hot_preload_n": point.margin_to_min_hot_preload_n,
                "status": status,
                "is_selected": abs(point.shim_mm - selected_shim) < 1e-9,
            }
        )

    return rows


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


@app.route("/tapered-preload", methods=["GET", "POST"])
def tapered_preload():
    inputs = TAPERED_DEFAULT_INPUTS.copy()
    result = None
    summary = None
    point_rows = []
    error_message = None

    if request.method == "POST":
        try:
            inputs = parse_tapered_inputs(request.form)
            result = calculate_tapered_preload(build_tapered_preload_inputs(inputs))
            summary = build_tapered_summary(inputs, result)
            point_rows = build_tapered_point_rows(inputs, result)
        except ValueError as exc:
            error_message = str(exc)

    return render_template(
        "tapered_preload.html",
        input_groups=TAPERED_PRELOAD_INPUT_GROUPS,
        inputs=inputs,
        result=result,
        summary=summary,
        point_rows=point_rows,
        error_message=error_message,
        parameter_notes=tapered_parameter_notes(),
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
