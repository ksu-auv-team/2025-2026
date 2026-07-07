# @file partials.py
# @brief HTMX partial routes for the AUV data visualizer.
#
# HTMX partials are small HTML snippets the server returns so HTMX can
# swap them into the page without a full reload or any JavaScript fetch calls.
#
# Two types of routes live here:
#   - /partials/<table>/rows       returns HTML  → HTMX swaps into <tbody>
#   - /partials/<table>/chart-data returns JSON  → Chart.js reads it
#
# DB API endpoints used (from smoke_test.sh):
#   GET  /<table>         → {"items": [...], "total": N, "limit": N, "offset": N}
#   GET  /<table>/latest  → single row dict
#   POST /<table>         → form data (NOT json), returns inserted row
#
# Tables + fields:
#   inputs       SURGE SWAY HEAVE ROLL PITCH YAW S1 S2 S3 ARM
#   outputs      MOTOR1 MOTOR2 MOTOR3 MOTOR4 VERTICAL_THRUST S1 S2 S3
#   imu          ACCEL_X ACCEL_Y ACCEL_Z GYRO_X GYRO_Y GYRO_Z MAG_X MAG_Y MAG_Z
#   depth        DEPTH
#   hydrophone   HEADING
#   power_safety B1_VOLTAGE B2_VOLTAGE B3_VOLTAGE
#                B1_CURRENT B2_CURRENT B3_CURRENT
#                B1_TEMP B2_TEMP B3_TEMP

from quart import Blueprint, current_app, render_template, request, jsonify
import httpx

partials_bp = Blueprint("partials", __name__, url_prefix="/partials")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def fetch(path: str, limit: int = 50) -> list[dict]:
    """
    GET rows from the DB API at `path`.

    Handles both response shapes the DB API can return:
      bare list  →  [{...}, {...}]
      envelope   →  {"items": [{...}], "total": N, ...}

    Returns [] instead of raising so every partial still renders
    with an empty-state row if the DB API is down.
    """
    #base = current_app.config["DB_API"]
    base= "http://127.0.0.1:8000"
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base}{path}", params={"limit": limit}, timeout=5)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("items", [])
    except Exception as exc:
        current_app.logger.warning(f"fetch({path}) failed: {exc}")
        return []


async def forward_post(path: str) -> tuple[dict, int]:
    """
    Forward a form POST from the visualizer browser to the DB API.

    The DB API expects application/x-www-form-urlencoded (form data),
    NOT JSON — this matches how the smoke_test.sh curl commands work.

    Returns (response_dict, http_status_code).
    """
    base = current_app.config["DB_API"]
    form = await request.form
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{base}{path}", data=dict(form), timeout=5)
            return r.json(), r.status_code
    except Exception as exc:
        current_app.logger.error(f"forward_post({path}) failed: {exc}")
        return {"error": str(exc)}, 502


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

@partials_bp.get("/inputs/rows")
async def inputs_rows():
    rows = await fetch("/inputs")
    return await render_template("partials/inputs_rows.html", rows=rows)


@partials_bp.post("/inputs")
async def post_input():
    """
    Called by the inputs form via hx-post="/partials/inputs".
    Forwards the form to the DB API, then returns fresh table rows
    so HTMX immediately reflects the new entry.
    """
    _, status = await forward_post("/inputs")
    rows = await fetch("/inputs")
    return await render_template("partials/inputs_rows.html", rows=rows), (200 if status in (200, 201) else status)


@partials_bp.get("/inputs/chart-data")
async def inputs_chart_data():
    rows = list(reversed(await fetch("/inputs", limit=60)))  # oldest first
    return jsonify({
        "labels": [r.get("TIMESTAMP", "") for r in rows],
        "surge":  [r.get("SURGE",  0) for r in rows],
        "sway":   [r.get("SWAY",   0) for r in rows],
        "heave":  [r.get("HEAVE",  0) for r in rows],
        "yaw":    [r.get("YAW",    0) for r in rows],
    })


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------

@partials_bp.get("/outputs/rows")
async def outputs_rows():
    rows = await fetch("/outputs")
    return await render_template("partials/outputs_rows.html", rows=rows)


@partials_bp.post("/outputs")
async def post_output():
    _, status = await forward_post("/outputs")
    rows = await fetch("/outputs")
    return await render_template("partials/outputs_rows.html", rows=rows), (200 if status in (200, 201) else status)


@partials_bp.get("/outputs/chart-data")
async def outputs_chart_data():
    rows = list(reversed(await fetch("/outputs", limit=60)))
    return jsonify({
        "labels":          [r.get("TIMESTAMP",       "") for r in rows],
        "motor1":          [r.get("MOTOR1",           0) for r in rows],
        "motor2":          [r.get("MOTOR2",           0) for r in rows],
        "motor3":          [r.get("MOTOR3",           0) for r in rows],
        "motor4":          [r.get("MOTOR4",           0) for r in rows],
        "vertical_thrust": [r.get("VERTICAL_THRUST",  0) for r in rows],
    })


# ---------------------------------------------------------------------------
# imu
# ---------------------------------------------------------------------------

@partials_bp.get("/imu/rows")
async def imu_rows():
    rows = await fetch("/imu")
    return await render_template("partials/imu_rows.html", rows=rows)


@partials_bp.get("/imu/chart-data")
async def imu_chart_data():
    rows = list(reversed(await fetch("/imu", limit=60)))
    return jsonify({
        "labels":  [r.get("TIMESTAMP", "") for r in rows],
        "accel_x": [r.get("ACCEL_X",   0) for r in rows],
        "accel_y": [r.get("ACCEL_Y",   0) for r in rows],
        "accel_z": [r.get("ACCEL_Z",   0) for r in rows],
        "gyro_x":  [r.get("GYRO_X",    0) for r in rows],
        "gyro_y":  [r.get("GYRO_Y",    0) for r in rows],
        "gyro_z":  [r.get("GYRO_Z",    0) for r in rows],
    })


# ---------------------------------------------------------------------------
# depth
# ---------------------------------------------------------------------------

@partials_bp.get("/depth/rows")
async def depth_rows():
    rows = await fetch("/depth")
    return await render_template("partials/depth_rows.html", rows=rows)


@partials_bp.get("/depth/chart-data")
async def depth_chart_data():
    rows = list(reversed(await fetch("/depth", limit=60)))
    return jsonify({
        "labels": [r.get("TIMESTAMP", "") for r in rows],
        "depth":  [r.get("DEPTH",      0) for r in rows],
    })


# ---------------------------------------------------------------------------
# hydrophone
# ---------------------------------------------------------------------------

@partials_bp.get("/hydrophone/rows")
async def hydrophone_rows():
    rows = await fetch("/hydrophone")
    return await render_template("partials/hydrophone_rows.html", rows=rows)


# ---------------------------------------------------------------------------
# power_safety
# ---------------------------------------------------------------------------

@partials_bp.get("/power_safety/rows")
async def power_safety_rows():
    rows = await fetch("/power_safety")
    return await render_template("partials/power_safety_rows.html", rows=rows)


@partials_bp.get("/power_safety/chart-data")
async def power_safety_chart_data():
    rows = list(reversed(await fetch("/power_safety", limit=60)))
    return jsonify({
        "labels":     [r.get("TIMESTAMP",  "") for r in rows],
        "b1_voltage": [r.get("B1_VOLTAGE",  0) for r in rows],
        "b2_voltage": [r.get("B2_VOLTAGE",  0) for r in rows],
        "b3_voltage": [r.get("B3_VOLTAGE",  0) for r in rows],
        "b1_temp":    [r.get("B1_TEMP",     0) for r in rows],
        "b2_temp":    [r.get("B2_TEMP",     0) for r in rows],
        "b3_temp":    [r.get("B3_TEMP",     0) for r in rows],
    })