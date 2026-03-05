"""
@file bno08x_serial.py
@brief Read BNO08x packets from a microcontroller over a serial cable and return parsed JSON.
@details
  Expects lines like:
      {X_Vel,Y_Vel,Z_Vel,Roll,Pitch,Yaw}
  where each field is an integer in [0..256] with 127 ~ center.
  This matches the Arduino sketch that prints one packet per line via Serial.println().

  The parser:
    - Reads newline-terminated lines from the serial port.
    - Validates the brace-enclosed, comma-separated format.
    - Converts the six values to integers, clamps to [0..256].
    - Returns a Python dict (JSON-serializable) with:
        * raw: original 0..256 values
        * signed: values centered at 0 by subtracting 127 (range ~[-127..+129])
        * engineering units (optional back-conversion):
            - vel_ms: velocities in m/s (requires VEL_MAX to match MCU)
            - euler_deg: angles in degrees, assuming MCU mapped [-180..+180] → [0..256]

  Adjust VEL_MAX_MPS if your Arduino code uses a different velocity scale.
"""

import os
import json
import serial
from typing import Optional, Dict, Any


class BNO08xSerial:
    """
    @brief Serial interface helper for BNO08x data from a microcontroller.
    @details
      Reads ASCII lines in the format "{x,y,z,roll,pitch,yaw}" where each value is 0..256.
      Provides convenience methods to return parsed data as JSON/dict.
    """

    # Must match the scale used on the microcontroller (Arduino sketch).
    VEL_MAX_MPS: float = 2.0  # [-VEL_MAX, +VEL_MAX] ↔ [0..256]

    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 115200, timeout: float = 1.0):
        """
        @brief Constructor initializes (but does not necessarily open) the serial port.
        @param port Serial device path (e.g., '/dev/ttyACM0', '/dev/ttyUSB0', 'COM3').
        @param baudrate Serial baud rate; must match the microcontroller.
        @param timeout Read timeout in seconds for non-blocking behavior.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        # Defer opening until connect() to allow error handling and port changes.
        self.serial: Optional[serial.Serial] = None

    def connect(self) -> None:
        """
        @brief Open the serial port if not already open.
        """
        if self.serial is None:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        elif not self.serial.is_open:
            self.serial.open()
        # Optional: flush any stale bytes
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def disconnect(self) -> None:
        """
        @brief Close the serial port if open.
        """
        if self.serial is not None and self.serial.is_open:
            self.serial.close()

    @staticmethod
    def _clamp_uint8_257(v: int) -> int:
        """
        @brief Clamp an integer to [0..256].
        """
        return 0 if v < 0 else 256 if v > 256 else v

    @staticmethod
    def _signed_from_center(v: int) -> int:
        """
        @brief Convert 0..256 value to signed around 0 by subtracting 127.
        @param v Integer in [0..256].
        @return Approx. [-127..+129] centered at 0.
        """
        return int(v) - 127

    @classmethod
    def _vel_from_u256(cls, v: int) -> float:
        """
        @brief Convert 0..256 back to velocity in m/s using symmetric range [-VEL_MAX, +VEL_MAX].
        """
        t = float(v) / 256.0  # [0..1]
        return (t * (2.0 * cls.VEL_MAX_MPS)) - cls.VEL_MAX_MPS

    @staticmethod
    def _deg_from_u256(v: int) -> float:
        """
        @brief Convert 0..256 back to degrees assuming mapping [-180..+180] → [0..256].
        """
        t = float(v) / 256.0  # [0..1]
        return (t * 360.0) - 180.0

    def _readline(self) -> Optional[str]:
        """
        @brief Read one line from the serial port (non-blocking up to timeout).
        @return Decoded line as UTF-8 string, or None on timeout/empty.
        """
        if self.serial is None or not self.serial.is_open:
            self.connect()
        line = self.serial.readline()  # type: ignore # bytes up to '\n' (or timeout)
        if not line:
            return None
        try:
            return line.decode("utf-8", errors="ignore").strip()
        except Exception:
            return None

    @staticmethod
    def _parse_packet(line: str) -> Optional[Dict[str, int]]:
        """
        @brief Parse a line like "{12,34,56,78,90,123}" into six integers 0..256.
        @param line Input line (already stripped).
        @return Dict with raw integer fields or None if invalid.
        """
        if not (line.startswith("{") and line.endswith("}")):
            return None
        body = line[1:-1].strip()
        parts = body.split(",")
        if len(parts) != 6:
            return None
        try:
            vals = [BNO08xSerial._clamp_uint8_257(int(p.strip())) for p in parts]
        except ValueError:
            return None

        return {
            "X_vel_u": vals[0],
            "Y_vel_u": vals[1],
            "Z_vel_u": vals[2],
            "Roll_u":  vals[3],
            "Pitch_u": vals[4],
            "Yaw_u":   vals[5],
        }

    def get_data(self) -> Optional[Dict[str, Any]]:
        """
        @brief Read one packet from the serial port and return parsed JSON-friendly dict.
        @details
          Returns a dictionary containing:
            - raw (0..256 ints)
            - signed (centered around 0)
            - vel_ms (reconstructed m/s using VEL_MAX_MPS)
            - euler_deg (reconstructed degrees, assuming [-180..180] mapping)
        @return Dict or None (if no valid line received within timeout).
        """
        line = self._readline()
        if line is None:
            return None

        pkt = self._parse_packet(line)
        if pkt is None:
            return None

        # Raw 0..256
        x_u = pkt["X_vel_u"]; y_u = pkt["Y_vel_u"]; z_u = pkt["Z_vel_u"]
        r_u = pkt["Roll_u"];  p_u = pkt["Pitch_u"]; yv_u = pkt["Yaw_u"]

        # Signed around zero
        x_s = self._signed_from_center(x_u)
        y_s = self._signed_from_center(y_u)
        z_s = self._signed_from_center(z_u)
        r_s = self._signed_from_center(r_u)
        p_s = self._signed_from_center(p_u)
        yv_s = self._signed_from_center(yv_u)

        # Engineering units
        x_ms = self._vel_from_u256(x_u)
        y_ms = self._vel_from_u256(y_u)
        z_ms = self._vel_from_u256(z_u)

        roll_deg  = self._deg_from_u256(r_u)
        pitch_deg = self._deg_from_u256(p_u)
        yaw_deg   = self._deg_from_u256(yv_u)

        return {
            "raw": {
                "X_vel_u": x_u, "Y_vel_u": y_u, "Z_vel_u": z_u,
                "Roll_u": r_u, "Pitch_u": p_u, "Yaw_u": yv_u
            },
            "signed": {
                "X_vel": x_s, "Y_vel": y_s, "Z_vel": z_s,
                "Roll": r_s, "Pitch": p_s, "Yaw": yv_s
            },
            "vel_ms": {
                "X_vel": x_ms, "Y_vel": y_ms, "Z_vel": z_ms
            },
            "euler_deg": {
                "Roll": roll_deg, "Pitch": pitch_deg, "Yaw": yaw_deg
            },
            "line": line  # optional: keep original line for debugging
        }

    def get_data_json_str(self) -> Optional[str]:
        """
        @brief Convenience wrapper to return the parsed packet as a JSON string.
        @return JSON string or None if no valid packet was received.
        """
        data = self.get_data()
        if data is None:
            return None
        else:
            return json.dumps(data)


class BNO08xI2C:
    def __init__(self, bus, address: int = 0x4B):
        pass