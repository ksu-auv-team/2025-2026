"""
@file bno08x_serial.py
@brief Read BNO08x packets from a microcontroller over a serial cable and return parsed JSON.
@details
  Expects lines like:
      {accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z,mag_x,mag_y,mag_z}
  where each field is an integer in [0..256] with 127 ~ center.
  This matches the Arduino sketch that prints one packet per line via Serial.println().

  The parser:
    - Reads newline-terminated lines from the serial port.
    - Validates the brace-enclosed, comma-separated format.
    - Converts the nine values to integers, clamps to [0..256].
    - Returns a Python dict (JSON-serializable) with:
        * raw: original 0..256 values  
        * ACCEL_X/Y/Z: accelerometer readings (signed, centered at 0)
        * GYRO_X/Y/Z: gyroscope readings (signed, centered at 0)
        * MAG_X/Y/Z: magnetometer readings (signed, centered at 0)

  This format matches the database IMU table schema.
"""

import os
import json
import serial
from typing import Optional, Dict, Any


class BNO08xSerial:
    """
    @brief Serial interface helper for BNO08x data from a microcontroller.
    @details
      Reads ASCII lines in the format "{ax,ay,az,gx,gy,gz,mx,my,mz}" where each value is 0..256.
      Provides convenience methods to return parsed data as JSON/dict matching the database schema.
    """

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
        @brief Parse a line like "{ax,ay,az,gx,gy,gz,mx,my,mz}" into nine integers 0..256.
        @param line Input line (already stripped).
        @return Dict with raw integer fields or None if invalid.
        """
        if not (line.startswith("{") and line.endswith("}")):
            return None
        body = line[1:-1].strip()
        parts = body.split(",")
        if len(parts) != 9:
            return None
        try:
            vals = [BNO08xSerial._clamp_uint8_257(int(p.strip())) for p in parts]
        except ValueError:
            return None

        return {
            "ACCEL_X_u": vals[0],
            "ACCEL_Y_u": vals[1],
            "ACCEL_Z_u": vals[2],
            "GYRO_X_u":  vals[3],
            "GYRO_Y_u":  vals[4],
            "GYRO_Z_u":  vals[5],
            "MAG_X_u":   vals[6],
            "MAG_Y_u":   vals[7],
            "MAG_Z_u":   vals[8],
        }

    def get_data(self) -> Optional[Dict[str, Any]]:
        """
        @brief Read one packet from the serial port and return parsed JSON-friendly dict.
        @details
          Returns a dictionary containing:
            - raw (0..256 ints for accel, gyro, mag)
            - ACCEL_X/Y/Z, GYRO_X/Y/Z, MAG_X/Y/Z (matching database schema)
        @return Dict or None (if no valid line received within timeout).
        """
        line = self._readline()
        if line is None:
            return None

        pkt = self._parse_packet(line)
        if pkt is None:
            return None

        # Raw 0..256 values
        ax_u = pkt["ACCEL_X_u"]; ay_u = pkt["ACCEL_Y_u"]; az_u = pkt["ACCEL_Z_u"]
        gx_u = pkt["GYRO_X_u"];  gy_u = pkt["GYRO_Y_u"];  gz_u = pkt["GYRO_Z_u"]
        mx_u = pkt["MAG_X_u"];   my_u = pkt["MAG_Y_u"];   mz_u = pkt["MAG_Z_u"]

        # Convert to signed values centered at zero
        ax_s = self._signed_from_center(ax_u)
        ay_s = self._signed_from_center(ay_u)
        az_s = self._signed_from_center(az_u)
        gx_s = self._signed_from_center(gx_u)
        gy_s = self._signed_from_center(gy_u)
        gz_s = self._signed_from_center(gz_u)
        mx_s = self._signed_from_center(mx_u)
        my_s = self._signed_from_center(my_u)
        mz_s = self._signed_from_center(mz_u)

        return {
            "raw": {
                "ACCEL_X_u": ax_u, "ACCEL_Y_u": ay_u, "ACCEL_Z_u": az_u,
                "GYRO_X_u": gx_u, "GYRO_Y_u": gy_u, "GYRO_Z_u": gz_u,
                "MAG_X_u": mx_u, "MAG_Y_u": my_u, "MAG_Z_u": mz_u
            },
            "ACCEL_X": float(ax_s),
            "ACCEL_Y": float(ay_s),
            "ACCEL_Z": float(az_s),
            "GYRO_X": float(gx_s),
            "GYRO_Y": float(gy_s),
            "GYRO_Z": float(gz_s),
            "MAG_X": float(mx_s),
            "MAG_Y": float(my_s),
            "MAG_Z": float(mz_s),
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