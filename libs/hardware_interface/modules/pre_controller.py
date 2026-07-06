import argparse
import time

from config import get_env
from quick_request import AUVClient

from hardware_interface.modules.ms5837 import MS5837

_BUS: int = int(get_env("I2C_BUS_NUMBER", required=True))


class PressureController:
    def __init__(self) -> None:
        self.auv_client = AUVClient()
        self.sensor = MS5837(bus=_BUS)
        if not self.sensor.init():
            raise RuntimeError("Failed to initialize MS5837 pressure sensor.")

    def update(self) -> None:
        """Read one measurement from the MS5837 and post depth (m) to the DB API."""
        if not self.sensor.read():
            print("MS5837 read error.")
            return

        self.auv_client.post("depth", DEPTH=self.sensor.depth())

    def run(self) -> None:
        """Continuously read the pressure sensor and publish depth to the DB API at 20 Hz."""
        try:
            while True:
                self.update()
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("PressureController stopped by user.")


def _test() -> None:
    """Read one depth measurement from the MS5837 without using the database."""
    print(f"Reading MS5837 pressure sensor on bus {_BUS}...")
    sensor = MS5837(bus=_BUS)
    if not sensor.init():
        print("Failed to initialize MS5837 pressure sensor.")
        return

    if not sensor.read():
        print("MS5837 read error.")
        return

    print(f"  Pressure : {sensor.pressure():.2f} mbar")
    print(f"  Temp     : {sensor.temperature():.2f} C")
    print(f"  Depth    : {sensor.depth():.3f} m")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pressure Controller — MS5837 depth sensor")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Read one depth measurement without the database",
    )
    args = parser.parse_args()

    if args.test:
        _test()
    else:
        PressureController().run()
