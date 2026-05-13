import argparse
import struct
import time

from auvsoftware.config import get_env
from auvsoftware.hardware_interface.i2c_commands import read as i2c_read
from auvsoftware.hardware_interface.i2c_commands import write as i2c_write
from auvsoftware.quick_request import AUVClient

_BUS: int = int(get_env("I2C_BUS_NUMBER", required=True))
_ADDRESS: int = int(get_env("IMU_ADDRESS", required=True).strip(), 16)

# SHTP channel numbers
_CH_EXEC    = 1
_CH_CONTROL = 2
_CH_INPUT   = 3

# BNO085 sensor report IDs
_REPORT_ACCEL = 0x01
_REPORT_GYRO  = 0x02
_REPORT_MAG   = 0x03

# Q-point scale factors: raw int16 * scale → SI units
_SCALE: dict[int, float] = {
    _REPORT_ACCEL: 2 ** -8,   # m/s²
    _REPORT_GYRO:  2 ** -9,   # rad/s
    _REPORT_MAG:   2 ** -4,   # µT
}

# Payload length (bytes) of each report type we care about
_REPORT_LEN: dict[int, int] = {
    _REPORT_ACCEL: 10,
    _REPORT_GYRO:  10,
    _REPORT_MAG:   10,
    0xF1: 5,   # timestamp rebase
    0xFB: 5,   # base timestamp reference
}


class _BNO085:
    """Minimal SHTP/I2C driver for the BNO085."""

    def __init__(self, bus: int, address: int) -> None:
        self._bus  = bus
        self._addr = address
        self._seq  = [0] * 6  # outgoing sequence number per SHTP channel
        self._soft_reset()

    def _read_packet(self) -> tuple[int, bytes]:
        """Read one SHTP packet. Returns (channel, payload)."""
        header = i2c_read(self._bus, self._addr, 4)
        length = ((header[1] & 0x7F) << 8) | header[0]
        if length <= 4:
            return header[2], b""
        packet = i2c_read(self._bus, self._addr, length)
        return packet[2], bytes(packet[4:])

    def _write_packet(self, channel: int, payload: bytes) -> None:
        """Write one SHTP packet."""
        length = len(payload) + 4
        header = bytes([
            length & 0xFF,
            (length >> 8) & 0x7F,
            channel,
            self._seq[channel],
        ])
        self._seq[channel] = (self._seq[channel] + 1) & 0xFF
        i2c_write(self._bus, self._addr, header + payload)

    def _soft_reset(self) -> None:
        """Issue a soft reset via the executable channel, then drain startup packets."""
        self._write_packet(_CH_EXEC, bytes([0x01]))
        time.sleep(0.5)
        for _ in range(5):
            try:
                self._read_packet()
            except OSError:
                break

    def enable_feature(self, report_id: int, interval_us: int = 50_000) -> None:
        """Enable a sensor report at the given interval (µs)."""
        payload = struct.pack(
            "<BBBHIII",
            0xFD,         # Set Feature command
            report_id,
            0,            # feature flags
            0,            # change sensitivity (uint16)
            interval_us,  # report interval (uint32, µs)
            0,            # batch interval
            0,            # sensor-specific config
        )
        self._write_packet(_CH_CONTROL, payload)
        time.sleep(0.05)

    def poll(self) -> tuple[bool, dict[int, tuple[float, float, float]]]:
        """
        Read one SHTP packet and parse any 3-axis sensor reports.
        Returns (packet_available, {report_id: (x, y, z)}).
        packet_available is False when the sensor has no pending data.
        """
        try:
            channel, payload = self._read_packet()
        except OSError:
            return False, {}

        if not payload:
            return False, {}

        results: dict[int, tuple[float, float, float]] = {}
        if channel != _CH_INPUT:
            return True, results

        i = 0
        while i < len(payload):
            report_id = payload[i]
            report_len = _REPORT_LEN.get(report_id)
            if report_len is None or i + report_len > len(payload):
                break
            if report_id in _SCALE:
                rx, ry, rz = struct.unpack_from("<hhh", payload, i + 4)
                scale = _SCALE[report_id]
                results[report_id] = (rx * scale, ry * scale, rz * scale)
            i += report_len

        return True, results


class ImuController:
    def __init__(self) -> None:
        self.auv_client = AUVClient()
        self._sensor = _BNO085(_BUS, _ADDRESS)
        self._sensor.enable_feature(_REPORT_ACCEL)
        self._sensor.enable_feature(_REPORT_GYRO)
        self._sensor.enable_feature(_REPORT_MAG)
        self._accel: tuple[float, float, float] | None = None
        self._gyro:  tuple[float, float, float] | None = None
        self._mag:   tuple[float, float, float] | None = None

    def _drain(self) -> None:
        """Read all pending packets and keep the latest value for each sensor type."""
        for _ in range(30):
            received, reports = self._sensor.poll()
            if not received:
                break
            if _REPORT_ACCEL in reports:
                self._accel = reports[_REPORT_ACCEL]
            if _REPORT_GYRO in reports:
                self._gyro = reports[_REPORT_GYRO]
            if _REPORT_MAG in reports:
                self._mag = reports[_REPORT_MAG]

    def update(self) -> None:
        """Drain the sensor queue and post the latest full reading to the DB API."""
        self._drain()
        if self._accel is None or self._gyro is None or self._mag is None:
            return
        self.auv_client.post(
            "imu",
            ACCEL_X=self._accel[0], ACCEL_Y=self._accel[1], ACCEL_Z=self._accel[2],
            GYRO_X=self._gyro[0],   GYRO_Y=self._gyro[1],   GYRO_Z=self._gyro[2],
            MAG_X=self._mag[0],     MAG_Y=self._mag[1],     MAG_Z=self._mag[2],
        )

    def run(self) -> None:
        """Continuously read the BNO085 and publish IMU data to the DB API at 20 Hz."""
        try:
            while True:
                self.update()
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("ImuController stopped by user.")


def _test() -> None:
    """Read one full sample set from the BNO085 without using the database."""
    print(f"Connecting to BNO085 on bus {_BUS}, address {_ADDRESS:#04x}...")
    sensor = _BNO085(_BUS, _ADDRESS)
    sensor.enable_feature(_REPORT_ACCEL)
    sensor.enable_feature(_REPORT_GYRO)
    sensor.enable_feature(_REPORT_MAG)

    accel: tuple | None = None
    gyro:  tuple | None = None
    mag:   tuple | None = None

    deadline = time.monotonic() + 3.0
    while (time.monotonic() < deadline
           and (accel is None or gyro is None or mag is None)):
        received, reports = sensor.poll()
        if _REPORT_ACCEL in reports:
            accel = reports[_REPORT_ACCEL]
        if _REPORT_GYRO in reports:
            gyro = reports[_REPORT_GYRO]
        if _REPORT_MAG in reports:
            mag = reports[_REPORT_MAG]
        if received:
            time.sleep(0.01)

    print(f"  Accel (m/s²):  {accel}")
    print(f"  Gyro  (rad/s): {gyro}")
    print(f"  Mag   (µT):    {mag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IMU Controller — BNO085")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Read one sample without the database",
    )
    args = parser.parse_args()

    if args.test:
        _test()
    else:
        ImuController().run()
