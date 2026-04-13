# GET / → renders index.html

from quart import Blueprint, render_template

pages_bp = Blueprint("pages", __name__)

@pages_bp.get("/")
async def index():
    return await render_template("index.html")