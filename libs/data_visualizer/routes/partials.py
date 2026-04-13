# all HTMX partial routes (tables, charts)
# TODO add all revelant paths and get them working properly

from quart import Blueprint, current_app, render_template
import httpx

partials_bp = Blueprint("partials", __name__, url_prefix="/partials")

async def fetch(path: str) -> list:
    base = current_app.config["DB_API"]
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{base}{path}", timeout=5)
        r.raise_for_status()
        data = r.json()
        # handle both bare list and {"items": [...]} envelope
        return data if isinstance(data, list) else data.get("items", [])

# --- Tables ---
@partials_bp.get("/inputs/rows")
async def inputs_rows():
    rows = await fetch("/inputs/")
    return await render_template("partials/inputs_rows.html", rows=rows)

@partials_bp.get("/outputs/rows")
async def outputs_rows():
    rows = await fetch("/outputs/")
    return await render_template("partials/outputs_rows.html", rows=rows)

@partials_bp.get("/imu/rows")
async def imu_rows():
    rows = await fetch("/imu/")
    return await render_template("partials/imu_rows.html", rows=rows)

# ... same pattern for batteries, sonar, externals, internals