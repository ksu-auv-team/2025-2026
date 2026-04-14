from quart import Quart
# from config_loader import load_config
from routes.pages import pages_bp
from routes.partials import partials_bp


# add a config loader later
def create_app():
    app = Quart(__name__)
    # config = load_config("data_visualizer")
    # app.config["DB_API"] = f"http://{config['dbhost']}:{config['dbport']}"
    # app.config["CAM_URL"] = config.get("camera_base_url", "http://localhost:5001")
    app.register_blueprint(pages_bp)
    app.register_blueprint(partials_bp)
    return app
