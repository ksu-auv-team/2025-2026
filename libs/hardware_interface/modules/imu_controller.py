import argparse
import struct
import time

from config import get_env
from hardware_interface.i2c_commands import read as i2c_read
from quick_request import AUVClient

_BUS: int = int(get_env("I2C_BUS_NUMBER", required=True))
_ADDRESS: int = int(get_env("IMU_ADDRESS", required=True).strip(), 16)

# 14-byte packet from the IMU Pico:
# index(u8) yaw(i16) pitch(i16) roll(i16) ax(i16) ay(i16) az(i16) accuracy(u8)
_PACKET_LEN = 14
_PACKET_FMT = "<BhhhhhhB"

# Raw value ranges used for 0-255 linear mapping
_ANGLE_RANGE = (-18000, 18000)  # 1/100°, per protocol spec
_ACCEL_RANGE = (-3924, 3924)    # 1/100 m/s², ±4 g
_ACCURACY_RANGE = (0, 3)


def _to_u8(value: int | float, lo: float, hi: float) -> int:
    """Map value from [lo, hi] to 0-255, clamping out-of-range inputs."""
    clamped = max(lo, min(hi, value))
    return round((clamped - lo) / (hi - lo) * 255)


class ImuController:
    def __init__(self) -> None:
        self.auv_client = AUVClient()

    def update(self) -> None:
        """Read one IMU packet from the Pico and post mapped values to the DB API."""
        try:
            raw = i2c_read(_BUS, _ADDRESS, _PACKET_LEN)
        except OSError as e:
            print(f"IMU I2C read error: {e}")
            return

        if len(raw) != _PACKET_LEN:
            return

        _, yaw, pitch, roll, ax, ay, az, accuracy = struct.unpack(_PACKET_FMT, raw)

        self.auv_client.post(
            "imu",
            ACCEL_X=_to_u8(ax, *_ACCEL_RANGE),
            ACCEL_Y=_to_u8(ay, *_ACCEL_RANGE),
            ACCEL_Z=_to_u8(az, *_ACCEL_RANGE),
            GYRO_X=_to_u8(yaw, *_ANGLE_RANGE),
            GYRO_Y=_to_u8(pitch, *_ANGLE_RANGE),
            GYRO_Z=_to_u8(roll, *_ANGLE_RANGE),
            MAG_X=0, MAG_Y=0, MAG_Z=0,
        )

    def run(self) -> None:
        """Continuously read the IMU Pico and publish data to the DB API at 20 Hz."""
        try:
            while True:
                self.update()
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("ImuController stopped by user.")


def _test() -> None:
    """Read one IMU packet from the Pico without using the database."""
    print(f"Reading IMU packet on bus {_BUS}, address {_ADDRESS:#04x}...")
    raw = i2c_read(_BUS, _ADDRESS, _PACKET_LEN)
    if len(raw) != _PACKET_LEN:
        print(f"Unexpected packet length: {len(raw)}")
        return

    idx, yaw, pitch, roll, ax, ay, az, accuracy = struct.unpack(_PACKET_FMT, raw)
    print(f"  Frame index : {idx}")
    print(f"  ACCEL_X     : {ax / 100:.2f} m/s²  → {_to_u8(ax, *_ACCEL_RANGE)}")
    print(f"  ACCEL_Y     : {ay / 100:.2f} m/s²  → {_to_u8(ay, *_ACCEL_RANGE)}")
    print(f"  ACCEL_Z     : {az / 100:.2f} m/s²  → {_to_u8(az, *_ACCEL_RANGE)}")
    print(f"  GYRO_X (yaw)  : {yaw / 100:.2f}°  → {_to_u8(yaw, *_ANGLE_RANGE)}")
    print(f"  GYRO_Y (pitch): {pitch / 100:.2f}°  → {_to_u8(pitch, *_ANGLE_RANGE)}")
    print(f"  GYRO_Z (roll) : {roll / 100:.2f}°  → {_to_u8(roll, *_ANGLE_RANGE)}")
    print(f"  MAG_X/Y/Z   : 0 / 0 / 0")
    print(f"  Accuracy    : {accuracy}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IMU Controller — Pico bridge")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Read one packet without the database",
    )
    args = parser.parse_args()

    if args.test:
        _test()
    else:
        ImuController().run()
