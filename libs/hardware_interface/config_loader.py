import json
import os

def load_config(app_name : str) -> dict:
    project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    project_config_path = os.path.join(project_path, "config/local_configs/hardware_interface.json")
    global_config_path = os.path.join(project_path, "config/global_config.json")
    if not os.path.exists(project_config_path):
        raise FileNotFoundError(f"Configuration file {project_config_path} does not exist.")

    with open(project_config_path) as f:
        project_config = json.load(f)

    with open(global_config_path) as f:
        global_config = json.load(f)

    # Merge project config with global config
    merged_config = {**global_config, **project_config}
    return merged_config