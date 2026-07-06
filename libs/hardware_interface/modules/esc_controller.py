import argparse
import time

from config import get_env
from hardware_interface.i2c_commands import write
from quick_request import AUVClient

_BUS: int = int(get_env("I2C_BUS_NUMBER", required=True))
_ADDRESS: int = int(get_env("ESC_ADDRESS", required=True), 16)

_REGISTER: int = 0x00
_MIN: int = 0
_MAX: int = 255
_NEUTRAL: int = 127


def _clamp(value: float) -> int:
    return max(_MIN, min(_MAX, round(value)))


def set_thrust(
    motor1: float, motor2: float, motor3: float, motor4: float,
    motor5: float, motor6: float, motor7: float, motor8: float,
) -> None:
    """Send thrust values (0-255) for all 8 motors via Pico over I2C."""
    motors = (motor1, motor2, motor3, motor4, motor5, motor6, motor7, motor8)
    thrusts = [_clamp(v) for v in motors]
    payload = bytes([_REGISTER, *thrusts])
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
            data.get("MOTOR5", _NEUTRAL),
            data.get("MOTOR6", _NEUTRAL),
            data.get("MOTOR7", _NEUTRAL),
            data.get("MOTOR8", _NEUTRAL),
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
        f"address {_ADDRESS:#04x}...",
    )
    try:
        set_thrust(
            _NEUTRAL, _NEUTRAL, _NEUTRAL, _NEUTRAL,
            _NEUTRAL, _NEUTRAL, _NEUTRAL, _NEUTRAL,
        )
        print("OK — payload delivered successfully.")
    except OSError as e:
        print(f"I2C error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ESC Controller")
    parser.add_argument(
        "--test", 
        action="store_true", 
        help="Send neutral thrust values without the database",
    )
    args = parser.parse_args()

    if args.test:
        _test()
    else:
        ESCController().run()