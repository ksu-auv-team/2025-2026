import time

from ..quick_request import AUVClient
from ..config import get_env
from .pid import PIDController

# --- Globals ---

PID = PIDController()

def _neutral() -> int:
    return int(get_env("MOTOR_NEUTRAL", "127"))

def _disarmed() -> dict:
    n = _neutral()
    return {
        "MOTOR1": n, "MOTOR2": n, "MOTOR3": n, "MOTOR4": n,
        "MOTOR5": n, "MOTOR6": n, "MOTOR7": n, "MOTOR8": n,
        "S1": n, "S2": n, "S3": n,
    }

# --- Helpers ---

def remap(value: float, in_min: float = -1.0, in_max: float = 1.0,
          out_min: float = 0, out_max: float = 255) -> int:
    """
    Clamp `value` to [in_min, in_max], then linearly map it to [out_min, out_max].

    Example: remap(0.0) -> 127 (midpoint of default range)
    """
    # Clamp input to the valid range
    clamped = max(in_min, min(in_max, float(value)))

    # Normalize to 0-1, then scale to output range
    normalized = (clamped - in_min) / (in_max - in_min)
    scaled = normalized * (out_max - out_min) + out_min

    return int(round(scaled))

# --- Core functions ---

def call_inputs(client: AUVClient) -> dict | None:
    return client.latest("inputs")

def generate_outputs(inputs: dict | None) -> dict:
    if not inputs or not inputs.get("ARM"):
        return _disarmed()

    PID.update_motors(
        x=float(inputs.get("SURGE", 0)),
        y=float(inputs.get("SWAY", 0)),
        z=float(inputs.get("HEAVE", 0)),
        yaw=float(inputs.get("YAW", 0)),
    )

    motors = PID.as_list_flat()  # [M1..M8] in [-1, 1]

    try:
        s1, s2, s3 = PID.servos.tolist()
    except Exception:
        s1 = s2 = s3 = 0.0

    return {
        "MOTOR1": remap(motors[0]), "MOTOR2": remap(motors[1]),
        "MOTOR3": remap(motors[2]), "MOTOR4": remap(motors[3]),
        "MOTOR5": remap(motors[4]), "MOTOR6": remap(motors[5]),
        "MOTOR7": remap(motors[6]), "MOTOR8": remap(motors[7]),
        "S1": remap(s1), "S2": remap(s2), "S3": remap(s3),
    }

def send_outputs(client: AUVClient, outputs: dict) -> None:
    client.post("outputs", **outputs)

# --- Entry point ---

def run() -> None:
    host     = get_env("AUV_HOST", "localhost")
    port     = get_env("AUV_PORT", "8000")
    poll_hz  = float(get_env("MOVEMENT_POLL_HZ", "50"))
    interval = 1.0 / max(poll_hz, 1.0)

    client = AUVClient(f"http://{host}:{port}")
    while True:
        inputs  = call_inputs(client)
        outputs = generate_outputs(inputs)
        send_outputs(client, outputs)
        time.sleep(interval)
