from quick_request import AUVClient
from pid import PIDController

# --- Globals ---

PID = PIDController()

DISARMED = {
    "step_index": 0,
    "M1": 127, "M2": 127, "M3": 127, "M4": 127,
    "M5": 127, "M6": 127, "M7": 127, "M8": 127,
    "S1": 127, "S2": 127, "S3": 127,
    "arm": False
}

# --- Helpers ---

def remap(value: float, in_min=-1.0, in_max=1.0, out_min=0, out_max=255) -> int:
    """Clamp then linearly map [-1, 1] → [0, 255]. 0.0 → 127."""
    value = max(in_min, min(in_max, float(value)))
    return int(round((value - in_min) / (in_max - in_min) * (out_max - out_min) + out_min))

# --- Core functions ---

def call_inputs(client: AUVClient) -> dict | None:
    return client.latest("inputs")

def generate_outputs(inputs: dict) -> dict:
    if not inputs or not inputs.get("arm"):
        return DISARMED

    PID.update_motors(
        x=float(inputs.get("x", 0)),
        y=float(inputs.get("y", 0)),
        z=float(inputs.get("z", 0)),
        yaw=float(inputs.get("yaw", 0)),
    )

    motors = PID.as_list_flat()  # [M1..M8] in [-1, 1]

    try:
        s1, s2, s3 = PID.servos.tolist()
    except Exception:
        s1 = s2 = s3 = 0.0

    return {
        "step_index": int(inputs.get("step_index", 0)),
        "M1": remap(motors[0]), "M2": remap(motors[1]),
        "M3": remap(motors[2]), "M4": remap(motors[3]),
        "M5": remap(motors[4]), "M6": remap(motors[5]),
        "M7": remap(motors[6]), "M8": remap(motors[7]),
        "S1": remap(s1), "S2": remap(s2), "S3": remap(s3),
        "arm": True
    }

def send_outputs(client: AUVClient, outputs: dict) -> None:
    client.post("outputs", outputs)

# --- Entry point ---

def run():
    client = AUVClient("http://192.168.1.10:8000")
    while True:
        inputs  = call_inputs(client)
        outputs = generate_outputs(inputs)
        send_outputs(client, outputs)