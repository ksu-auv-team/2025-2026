import time
from ..quick_request import AUVClient
from ..config import get_env
from libs.movement_package.movement_package import generate_outputs, send_outputs
from . import ai_manager
from . import straight_run_logic

# Set this to switch modes -- no runtime switching needed, so it's just a
# plain constant here rather than an env var/config option.
#   "mission"      -- run the gate/slalom mission plan (ai_manager.py)
#   "straight_run" -- run the straight_run_logic utility standalone
MODE = "straight_run"


def run() -> None:
    host     = get_env("AUV_HOST", "localhost")
    port     = get_env("AUV_PORT", "8000")
    poll_hz  = float(get_env("MOVEMENT_POLL_HZ", "50"))
    interval = 1.0 / max(poll_hz, 1.0)
    client = AUVClient(f"http://{host}:{port}")

    if MODE == "straight_run":
        active = straight_run_logic
    else:
        active = ai_manager

    while True:
        inputs = active.update(client)
        outputs = generate_outputs(inputs)
        send_outputs(client, outputs)
        time.sleep(interval)