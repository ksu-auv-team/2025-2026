import time

import smbus2

from libs.db_manager.models import OutputsRead
from libs.hardware_interface.db_connection import DB_BASE_URL, DBConnection

I2C_BUS = 7
I2C_ADDRESS = 8
DEFAULT_PWM = 127
POLL_INTERVAL = 0.05  # 50ms — Arduino loop runs every 20ms

# Order matches Arduino motorValues[0..4]: M1-M4 horizontal, M5 vertical
_MOTOR_FIELDS = ["MOTOR1", "MOTOR2", "MOTOR3", "MOTOR4", "VERTICAL_THRUST"]


def _clamp(val: int) -> int:
    return max(0, min(255, int(val)))


def _neutral() -> list[int]:
    return [DEFAULT_PWM] * 8


def _extract_motor_values(row: OutputsRead) -> list[int]:
    return [_clamp(getattr(row, field)) for field in _MOTOR_FIELDS]


def send_motor_values(bus: smbus2.SMBus, values: list[int]) -> None:
    # Arduino receiveEvent expects howMany==9: register byte (header) + 8 motor values.
    # write_i2c_block_data sends: [register] + values = 9 bytes total.
    bus.write_i2c_block_data(I2C_ADDRESS, 0x00, values)


def run(
    bus_number: int = I2C_BUS,
    db_url: str = DB_BASE_URL,
    poll_interval: float = POLL_INTERVAL,
) -> None:
    last_id: int | None = None

    with smbus2.SMBus(bus_number) as bus, DBConnection(db_url) as db:
        # Send neutral on startup so ESCs arm cleanly
        send_motor_values(bus, _neutral())

        while True:
            row = db.fetch_latest_outputs()

            if row is None:
                # DB unreachable — Arduino's 2s timeout will neutral itself; keep trying
                time.sleep(poll_interval)
                continue

            if row.ID != last_id:
                values = _extract_motor_values(row)
                send_motor_values(bus, values)
                last_id = row.ID

            time.sleep(poll_interval)


if __name__ == "__main__":
    run()
