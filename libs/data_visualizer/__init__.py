"""
@file __init__.py
@brief Quart application factory for the KSU AUV Data Visualizer.

This module exposes create_app which builds and configures the Flask app:
- Loads configuration via load_config(app_name)
- Registers routes and blueprints
- Serves templates and static assets

@note The static folder is "statics" and templates folder is "templates".
"""
