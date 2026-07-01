from ..quick_request import AUVClient
from libs.movement_package import movement_package

def get_sensor_data(client: AUVClient) -> dict | None:
    imu_data = client.latest("imu")
    depth_data = client.latest("depth")
    detections_data = client.latest("detections")

    all_data = imu_data | depth_data | detections_data
    return all_data



def run() -> None:
    host     = get_env("AUV_HOST", "localhost")
    port     = get_env("AUV_PORT", "8000")
    poll_hz  = float(get_env("MOVEMENT_POLL_HZ", "50"))
    interval = 1.0 / max(poll_hz, 1.0)

    client = AUVClient(f"http://{host}:{port}")
    while True:
        sensor_data  = get_sensor_data(client)

        ## ai logic to be inserted here
        ## send sensor data to ai logic module, obtain back inputs
        ## inputs = ai_logic(sensor_data)

        outputs = generate_outputs(inputs)
        send_outputs(client, outputs)
        time.sleep(interval)