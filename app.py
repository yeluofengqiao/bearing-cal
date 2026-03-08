import csv
import io
import os

from flask import Flask, Response, render_template, request

from bearing_model import Bearing6208CapacitanceModel


app = Flask(__name__)


DEFAULT_INPUTS = {
    "fr": 3000.0,
    "fa": 1500.0,
    "speed_rpm": 3000.0,
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
                "capacitance_pf": detail.capacitance_pf,
                "contact_angle_deg": detail.contact_angle_deg,
                "is_active": detail.load_q_n > 0,
            }
        )
    return rows


def parse_inputs(source):
    values = {}
    for key, default_value in DEFAULT_INPUTS.items():
        raw_value = source.get(key, default_value)
        values[key] = float(raw_value)
    return values


def build_summary(result, rows):
    active_rows = [row for row in rows if row["is_active"]]
    peak_load = max((row["load_q_n"] for row in active_rows), default=0.0)
    peak_capacitance = max((row["capacitance_pf"] for row in active_rows), default=0.0)
    return {
        "active_ball_count": len(active_rows),
        "peak_load_q_n": peak_load,
        "peak_ball_capacitance_pf": peak_capacitance,
        "solver_status": "求解收敛" if result.solver_converged else "求解未收敛",
    }


def run_calculation(inputs):
    model = Bearing6208CapacitanceModel()
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
            "film_thickness_um",
            "capacitance_pf",
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
                f"{row['capacitance_pf']:.6f}",
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
            if any(value < 0 for value in inputs.values()):
                raise ValueError("输入值不能为负数。")
            result, rows, summary = run_calculation(inputs)
        except ValueError as exc:
            error_message = str(exc)

    return render_template(
        "index.html",
        inputs=inputs,
        result=result,
        rows=rows,
        summary=summary,
        error_message=error_message,
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
            "Content-Disposition": "attachment; filename=bearing_6208_results.csv"
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
