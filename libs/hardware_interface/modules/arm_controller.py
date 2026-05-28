import argparse
import time

from config import get_env
from hardware_interface.i2c_commands import write
from quick_request import AUVClient

_BUS: int = int(get_env("I2C_BUS_NUMBER", required=True))
_ADDRESS: int = int(get_env("ARM_ADDRESS", required=True), 16)

_REGISTER: int = 0x00
_MIN: int = 0
_MAX: int = 255
_NEUTRAL: int = 127

def _clamp(value: int) -> int:
    return max(_MIN, min(_MAX, value))

def set_arm_position(val: int) -> None:
    """Send arm position value (0-255) to the arm controller via Pico over I2C."""
    clamped_val = _clamp(val)
    payload = bytes([_REGISTER, clamped_val])
    write(_BUS, _ADDRESS, payload)


class ArmController:
    def __init__(self) -> None:
        self.auv_client = AUVClient()

    def update(self) -> None:
        """Fetch the latest arm command from the API and send to the arm controller."""
        data = self.auv_client.latest("inputs")
        if data is None:
            print("No input commands available.")
            return

        # S1 is a boolean field (0=retracted, 1=extended)
        arm_position = _MAX if data.get("S1", 0) else _MIN
        set_arm_position(arm_position)

    def run(self) -> None:
        """Continuously update the arm controller with the latest commands from the API."""
        try:
            while True:
                self.update()
                time.sleep(0.05)  # 20 Hz
        except KeyboardInterrupt:
            print("ArmController stopped by user.")

def _test() -> None:
    """Send neutral position to the arm and confirm over I2C without the database."""
    print(
        f"Sending neutral ({_NEUTRAL}) to arm on bus {_BUS}, address {_ADDRESS:02X}...",
    )
    set_arm_position(_NEUTRAL)
    print("Test complete. Check I2C communication for confirmation.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Arm Controller for AUV")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run a test by sending neutral position to the arm controller",
    )
    args = parser.parse_args()

    if args.test:
        _test()
    else:
        controller = ArmController()
        controller.run()