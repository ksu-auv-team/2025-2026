# bno08x_serial.py
# Requires: pip install pyserial
from __future__ import annotations

import sys
import time
import struct
import logging
from dataclasses import dataclass, asdict
import serial  # type: ignore

# --- Framing constants ---
START1, START2 = b'B', b'R'
HDR_REST_LEN = 6  # len(2) + msg_id(2) + src(1) + dst(1)

# --- Msg IDs (must match firmware) ---
MSG_GET_IMU   = 0x0101
MSG_SET_HOME  = 0x0102
MSG_RESET_VEL = 0x0103
MSG_RESP_IMU  = 0x8101
MSG_ACK       = 0x8000
MSG_NACK      = 0x8001

DEFAULT_HOST_ID   = 0x00
DEFAULT_DEVICE_ID = 0x01


@dataclass
class IMUData:
    micros: int
    rv_status: int
    la_status: int
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    vx: float
    vy: float
    vz: float
    ax_lin: float
    ay_lin: float
    az_lin: float
    legacy_payload: bool

    def as_dict(self) -> dict:
        return asdict(self)


class BNO08x_Serial:
    """
    Host-side client for the Pico+BNO08x request/response protocol.

    Features:
      - get_imu(): Request one IMU sample (supports 42B new + 30B legacy payloads)
      - set_home_current(): Zero orientation to the current attitude
      - set_home_explicit(roll, pitch, yaw): Set home to provided R,P,Y (deg)
      - reset_velocity(): Zero the onboard velocity integrator
      - Context manager support and simple input flushing

    Example:
        with BNO08x_Serial('/dev/ttyACM0') as imu:
            print(imu.get_imu().as_dict())
            imu.set_home_current()
            print(imu.get_imu().as_dict())
            imu.reset_velocity()
    """

    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 115200,
        timeout: float = 1.0,
        host_id: int = DEFAULT_HOST_ID,
        device_id: int = DEFAULT_DEVICE_ID,
        logger: logging.Logger | None = None,
    ):
        self.port = port or self._default_port()
        self.baudrate = baudrate
        self.timeout = timeout
        self.host_id = host_id
        self.device_id = device_id
        self.log = logger or logging.getLogger(__name__)
        self.ser: serial.Serial | None = None

    # ---------- lifecycle ----------
    def open(self) -> None:
        if self.ser and self.ser.is_open:
            return
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        # Optional: small settle
        time.sleep(0.05)

    def close(self) -> None:
        if self.ser:
            try:
                self.ser.close()
            finally:
                self.ser = None

    def __enter__(self) -> "BNO08x_Serial":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------- high-level API ----------
    def get_imu(self) -> IMUData:
        ser = self._ensure_serial()
        self._flush_input()
        ser.write(self._build_get_imu())
        while True:
            msg_id, _src, _dst, payload = self._read_frame()
            if msg_id == MSG_RESP_IMU:
                return self._parse_resp_imu(payload)
            if msg_id == MSG_NACK:
                err = payload[0] if payload else 0
                raise RuntimeError(f"NACK from device (err={err})")
            # ignore any other frames

    def set_home_current(self) -> None:
        ser = self._ensure_serial()
        self._flush_input()
        ser.write(self._build_set_home_current())
        msg_id, *_ = self._read_frame()
        if msg_id != MSG_ACK:
            raise RuntimeError("SET_HOME current failed (no ACK)")

    def set_home_explicit(self, roll_deg: float, pitch_deg: float, yaw_deg: float) -> None:
        ser = self._ensure_serial()
        self._flush_input()
        ser.write(self._build_set_home_explicit(roll_deg, pitch_deg, yaw_deg))
        msg_id, *_ = self._read_frame()
        if msg_id != MSG_ACK:
            raise RuntimeError("SET_HOME explicit failed (no ACK)")

    def reset_velocity(self) -> None:
        ser = self._ensure_serial()
        self._flush_input()
        ser.write(self._build_reset_vel())
        msg_id, *_ = self._read_frame()
        if msg_id != MSG_ACK:
            raise RuntimeError("RESET_VEL failed (no ACK)")

    # Optional: simple generator for repeated polling
    def stream(self, period_s: float = 0.02):
        """Yield IMUData at a fixed poll rate (host-driven)."""
        next_t = time.perf_counter()
        while True:
            data = self.get_imu()
            yield data
            next_t += period_s
            dt = next_t - time.perf_counter()
            if dt > 0:
                time.sleep(dt)

    # ---------- framing / protocol ----------
    @staticmethod
    def _cksum16(b: bytes) -> int:
        return sum(b) & 0xFFFF

    def _build_frame(self, msg_id: int, payload: bytes = b"") -> bytes:
        hdr = START1 + START2
        hdr += struct.pack("<H", len(payload))
        hdr += struct.pack("<H", msg_id)
        hdr += struct.pack("BB", self.host_id, self.device_id)
        ck = (self._cksum16(hdr) + self._cksum16(payload)) & 0xFFFF
        return hdr + payload + struct.pack("<H", ck)

    def _build_get_imu(self) -> bytes:
        return self._build_frame(MSG_GET_IMU)

    def _build_set_home_current(self) -> bytes:
        return self._build_frame(MSG_SET_HOME)

    def _build_set_home_explicit(self, roll_deg: float, pitch_deg: float, yaw_deg: float) -> bytes:
        # Firmware expects R, P, Y (float32 LE)
        payload = struct.pack("<fff", roll_deg, pitch_deg, yaw_deg)
        return self._build_frame(MSG_SET_HOME, payload)

    def _build_reset_vel(self) -> bytes:
        return self._build_frame(MSG_RESET_VEL)

    def _read_exact(self, n: int) -> bytes:
        ser = self._ensure_serial()
        buf = b""
        while len(buf) < n:
            chunk = ser.read(n - len(buf))
            if not chunk:
                raise TimeoutError("Serial read timeout")
            buf += chunk
        return buf

    def _read_frame(self):
        ser = self._ensure_serial()
        # 1) find 'B','R'
        while True:
            b = ser.read(1)
            if not b:
                raise TimeoutError("Timeout waiting for start byte")
            if b == START1:
                b2 = ser.read(1)
                if b2 == START2:
                    break

        # 2) header remainder
        rest = self._read_exact(HDR_REST_LEN)  # len(2), id(2), src(1), dst(1)
        plen, msg_id, src, dst = struct.unpack("<H H B B", rest)
        if plen > 4096:
            raise ValueError(f"Unreasonable payload length: {plen}")

        # 3) payload + checksum
        payload = self._read_exact(plen) if plen else b""
        ck_rx = struct.unpack("<H", self._read_exact(2))[0]

        # 4) checksum
        ck_calc = (self._cksum16(START1 + START2 + rest) + self._cksum16(payload)) & 0xFFFF
        if ck_rx != ck_calc:
            raise ValueError(f"Checksum mismatch (rx={ck_rx:#06x}, calc={ck_calc:#06x})")

        return msg_id, src, dst, payload

    # ---------- payload parsing ----------
    def _parse_resp_imu(self, payload: bytes) -> IMUData:
        """
        New firmware (42 bytes):
          <I B B f f f f f f f f f>
          micros, rv_stat, la_stat,
          roll, pitch, yaw,     (deg)
          vx, vy, vz,           (m/s, body frame)
          ax_lin, ay_lin, az_lin (m/s^2, gravity-removed, body frame)

        Legacy firmware (30 bytes):
          <I B B f f f f f f>
          micros, rv_stat, acc_stat,
          yaw, pitch, roll,    (deg)
          ax, ay, az           (m/s^2, includes gravity)
        """
        if len(payload) == 42:
            micros, rv_stat, la_stat, roll, pitch, yaw, vx, vy, vz, ax_lin, ay_lin, az_lin = \
                struct.unpack("<IBBfffffffff", payload)
            return IMUData(
                micros=micros,
                rv_status=rv_stat,
                la_status=la_stat,
                roll_deg=roll,
                pitch_deg=pitch,
                yaw_deg=yaw,
                vx=vx, vy=vy, vz=vz,
                ax_lin=ax_lin, ay_lin=ay_lin, az_lin=az_lin,
                legacy_payload=False,
            )

        if len(payload) == 30:
            micros, rv_stat, acc_stat, yaw, pitch, roll, ax, ay, az = \
                struct.unpack("<IBBffffff", payload)
            # Map legacy to new fields (no velocity; accel includes gravity)
            return IMUData(
                micros=micros,
                rv_status=rv_stat,
                la_status=acc_stat,
                roll_deg=roll,
                pitch_deg=pitch,
                yaw_deg=yaw,
                vx=0.0, vy=0.0, vz=0.0,
                ax_lin=ax, ay_lin=ay, az_lin=az,
                legacy_payload=True,
            )

        raise ValueError(f"RESP_IMU payload length unexpected: {len(payload)} (expected 42 new or 30 legacy)")

    # ---------- helpers ----------
    def _flush_input(self) -> None:
        """Clear any buffered inbound bytes to avoid mixing frames."""
        ser = self._ensure_serial()
        ser.reset_input_buffer()

    def _ensure_serial(self) -> serial.Serial:
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port is not open. Call open() or use context manager.")
        return self.ser

    @staticmethod
    def _default_port() -> str:
        if sys.platform.startswith("linux"):
            return "/dev/ttyACM0"
        if sys.platform == "darwin":
            return "/dev/tty.usbmodem14401"
        if sys.platform == "win32":
            return "COM6"
        return "/dev/ttyACM0"


# ---------- standalone demo ----------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    port = None
    if len(sys.argv) >= 2:
        port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) >= 3 else 115200

    with BNO08x_Serial(port=port, baudrate=baud, timeout=1.0) as imu:
        while True:
            try:
                d = imu.get_imu()
                print(f"\rIMU: {d.as_dict()}", end="")  # Print in same spot, no newline

                time.sleep(0.1)  # Adjust polling rate as needed

            except Exception as e:
                print(f"Error occurred: {e}")
