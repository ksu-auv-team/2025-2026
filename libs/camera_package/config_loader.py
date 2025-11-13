# Placeholder if you want to load config files later
def load_config(path="config.json"):
    import json
    with open(path) as f:
        return json.load(f)
