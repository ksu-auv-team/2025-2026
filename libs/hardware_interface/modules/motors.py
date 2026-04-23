import time

import smbus2

from libs.db_manager.models import OutputsRead
from libs.hardware_interface.db_connection import DB_BASE_URL, DBConnection

I2C_BUS = 7
I2C_ADDRESS = 8
DEFAULT_PWM = 127
POLL_INTERVAL = 0.05  # 50ms — Arduino loop runs every 20ms
RETRY_INTERVAL = 1.0  # seconds between retries when Arduino is unreachable

# Order matches Arduino motorValues[0..4]: M1-M4 horizontal, M5 vertical
_MOTOR_FIELDS = ["MOTOR1", "MOTOR2", "MOTOR3", "MOTOR4", "VERTICAL_THRUST"]


def _clamp(val: int) -> int:
    return max(0, min(255, int(val)))


def _neutral() -> list[int]:
    return [DEFAULT_PWM] * len(_MOTOR_FIELDS)


def _extract_motor_values(row: OutputsRead) -> list[int]:
    return [_clamp(getattr(row, field)) for field in _MOTOR_FIELDS]


def send_motor_values(bus: smbus2.SMBus, values: list[int]) -> bool:
    # Arduino receiveEvent expects 6 bytes: register byte (header) + 5 motor values.
    # write_i2c_block_data sends: [register] + values = 6 bytes total.
    try:
        bus.write_i2c_block_data(I2C_ADDRESS, 0x00, values)
        return True
    except OSError as e:
        print(f"[motors] I2C error (address 0x{I2C_ADDRESS:02X} on bus {bus.fd}): {e}")
        return False


def run(
    bus_number: int = I2C_BUS,
    db_url: str = DB_BASE_URL,
    poll_interval: float = POLL_INTERVAL,
) -> None:
    last_id: int | None = None

    try:
        with smbus2.SMBus(bus_number) as bus, DBConnection(db_url) as db:
            print("[motors] Waiting for Arduino on I2C bus...")
            while not send_motor_values(bus, _neutral()):
                time.sleep(RETRY_INTERVAL)
            print("[motors] Arduino connected, motor loop running.")

            while True:
                row = db.fetch_latest_outputs()

                if row is None:
                    time.sleep(poll_interval)
                    continue

                if last_id != row.ID and send_motor_values(bus, _extract_motor_values(row)):
                    last_id = row.ID
                    values = _extract_motor_values(row)
                    print(f"[motors] Row {row.ID}: M1={values[0]} M2={values[1]} M3={values[2]} M4={values[3]} VERT={values[4]}")

                time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("[motors] Shutting down.")


if __name__ == "__main__":
    run()
