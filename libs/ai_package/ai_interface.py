import time
from ..quick_request import AUVClient
from ..config import get_env
from libs.movement_package.movement_package import generate_outputs, send_outputs
from . import ai_manager


def run() -> None:
    host     = get_env("AUV_HOST", "localhost")
    port     = get_env("AUV_PORT", "8000")
    poll_hz  = float(get_env("MOVEMENT_POLL_HZ", "50"))
    interval = 1.0 / max(poll_hz, 1.0)
    client = AUVClient(f"http://{host}:{port}")

    while True:
        inputs = ai_manager.update(client)
        outputs = generate_outputs(inputs)
        send_outputs(client, outputs)
        time.sleep(interval)