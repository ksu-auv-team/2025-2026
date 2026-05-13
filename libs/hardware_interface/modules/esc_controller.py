import argparse
import time

from auvsoftware.config import get_env
from auvsoftware.hardware_interface.i2c_commands import write
from auvsoftware.quick_request import AUVClient

_BUS: int = int(get_env("I2C_BUS_NUMBER", required=True))
_ADDRESS: int = int(get_env("ESC_ADDRESS", required=True), 16)

_REGISTER: int = 0x00
_MIN: int = 0
_MAX: int = 255
_NEUTRAL: int = 127


def _clamp(value: int) -> int:
    return max(_MIN, min(_MAX, value))


def set_thrust(motor1: int, motor2: int, motor3: int, motor4: int, vertical: int) -> None:
    """Send thrust values (0-255) to all motors via Pico over I2C."""
    thrusts = [_clamp(v) for v in (motor1, motor2, motor3, motor4, vertical)]
    payload = bytes([_REGISTER] + thrusts)
    write(_BUS, _ADDRESS, payload)


class ESCController:
    def __init__(self) -> None:
        self.auv_client = AUVClient()

    def update(self) -> None:
        """Fetch the latest desired thrust values from the API and send to ESCs."""
        data = self.auv_client.latest("outputs")
        if data is None:
            print("No output commands available.")
            return

        set_thrust(
            data.get("MOTOR1", _NEUTRAL),
            data.get("MOTOR2", _NEUTRAL),
            data.get("MOTOR3", _NEUTRAL),
            data.get("MOTOR4", _NEUTRAL),
            data.get("VERTICAL_THRUST", _NEUTRAL),
        )

    def run(self) -> None:
        """Continuously update ESCs with the latest commands from the API."""
        try:
            while True:
                self.update()
                time.sleep(0.05)  # 20 Hz
        except KeyboardInterrupt:
            print("ESCController stopped by user.")


def _test() -> None:
    """Send neutral thrust to all motors and confirm over I2C without the database."""
    print(
        f"Sending neutral ({_NEUTRAL}) to all motors on bus {_BUS},", 
        f"address {_ADDRESS:#04x}..."
    )
    try:
        set_thrust(_NEUTRAL, _NEUTRAL, _NEUTRAL, _NEUTRAL, _NEUTRAL)
        print("OK — payload delivered successfully.")
    except OSError as e:
        print(f"I2C error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESC Controller")
    parser.add_argument(
        "--test", 
        action="store_true", 
        help="Send neutral thrust values without the database"
    )
    args = parser.parse_args()

    if args.test:
        _test()
    else:
        ESCController().run()