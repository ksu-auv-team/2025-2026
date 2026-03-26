"""
@file __init__.py
@brief Quart application factory for the KSU AUV Data Visualizer.

This module exposes create_app which builds and configures the Flask app:
- Loads configuration via load_config(app_name)
- Registers routes and blueprints
- Serves templates and static assets

@note The static folder is "statics" and templates folder is "templates".
"""

from quart import Quart


DEFAULT_APP_NAME = "data_visualizer"


def create_app(app_name: str | None = None) -> Quart:

    APP_NAME = app_name or DEFAULT_APP_NAME

    app = Quart(
        __name__,
        static_folder="statics",
        template_folder="templates",
    )

    return app

