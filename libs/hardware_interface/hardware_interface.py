"""
@file hardware_interface.py
@brief Hardware interface orchestrating I2C devices and a serial IMU.
@details
  - Loads configuration and initializes I2C (smbus2) and serial IMU.
  - Probes configured I2C addresses using I2C_RDWR (adapter-friendly).
  - Skips probing write-only / RX-only devices (e.g., motor controller at 0x4C).
  - Runs two processes:
      * ControlProcess: fetches latest outputs from DB and forwards to controllers.
      * SensorProcess : reads IMU data over serial and posts to DB.
  - IMU values stored in engineering units (m/s and degrees).

@note Requires:
  - smbus2
  - a working .config_loader.load_config
  - .logic.sendDataToServer, .logic.getDataFromServer
  - .i2c_devices.BNO08x.BNO08x (class with get_data() / get_data_json_str())
"""

import time
import json
import logging
import multiprocessing
from typing import Optional, Tuple, Dict, Any, List

import smbus2
from smbus2 import i2c_msg

from .config_loader import load_config
from .logic import sendDataToServer, getDataFromServer
from .i2c_devices.BNO08x import BNO08xI2C, BNO08xSerial

import requests


def _to_addr(v) -> int:
    """
    @brief Convert config address (int or '0x..' string) to int.
    """
    return int(v, 0) if isinstance(v, str) else int(v)


def _probe_i2c_rdwr(bus: smbus2.SMBus, addr: int, read_len: int = 1) -> Tuple[bool, Optional[str]]:
    """
    @brief Probe an I2C address using I2C_RDWR read (adapter-friendly).
    @param bus Open smbus2.SMBus
    @param addr 7-bit I2C address
    @param read_len How many bytes to attempt to read
    @return (ok, error_string_or_None)
    """
    try:
        msg = i2c_msg.read(addr, read_len)
        bus.i2c_rdwr(msg)
        return True, None
    except OSError as e:
        # 121 = Remote I/O error (NACK) is common when nobody's home
        return False, f"[Errno {e.errno}] {e.strerror or 'I2C_RDWR failed'}"


class HardwareInterface:
    def __init__(self, qualify : bool = False):
        """
        @brief Initializes the hardware interface, loads configuration, and sets up the I2C bus.
        """
        logging.basicConfig(level=logging.INFO)
        self.config: Dict[str, Any] = load_config('config/hardware_config.json') #error handling for missing files? 
                                                                                 # make sure the file exists 

        # Initialize I2C bus
        self.bus = smbus2.SMBus(self.config['i2c_bus'])
        logging.info("Hardware Interface initialized with I2C bus %d", self.config['i2c_bus'])
        logging.info("Configuration loaded: %s", self.config)

        # Build skip set: devices you don't want to read-probe (RX-only / write-only controllers)
        skip_cfg = self.config.get('Skip_Probe_Addresses', [])
        skip_set = {_to_addr(a) for a in skip_cfg} if isinstance(skip_cfg, list) else set()
        if 'Motor_Controller_Address' in self.config:
            # Motor controller at 0x4C is RX-only: do not read-probe it
            try:
                skip_set.add(_to_addr(self.config['Motor_Controller_Address']))
            except Exception as e:
                logging.warning("Motor_Controller_Address invalid: %r (%s)", self.config['Motor_Controller_Address'], e)
        self._skip_probe_addrs = skip_set

        logging.info(
            "Checking hardware addresses (I2C_RDWR read probe; skipped: %s)...",
            [hex(a) for a in sorted(self._skip_probe_addrs)]
        )
        self.check_hardware_addresses()

        # Default input shadow (used only if DB empty)
        self.input_data: Dict[str, int] = {
            "M1": 127, "M2": 127, "M3": 127, "M4": 127,
            "M5": 127, "M6": 127, "M7": 127, "M8": 127,
            "S1": 127, "S2": 127, "S3": 127
        }

        # IMU in engineering units (m/s and degrees)
        self.sensor_data: Dict[str, Any] = {
            "IMU_Data": {
                "ACCEL_X": 0.0, "ACCEL_Y": 0.0, "ACCEL_Z": 0.0,
                "GYRO_X": 0.0, "GYRO_Y": 0.0, "GYRO_Z": 0.0,
                "MAG_X": 0.0, "MAG_Y": 0.0, "MAG_Z": 0.0
            },
            "Hydrophone_Data": {},
            "Power_Safety_Data": {}
        }


        # Serial IMU (Pico running Arduino sketch)
        self.bno08x = BNO08xSerial(
            port=self.config['BNO08x_Port'],
            baudrate=self.config['BNO08x_Baudrate'],
            timeout=self.config.get('BNO08x_Timeout', 1.0)
        )
        try:
            self.bno08x.connect()  # open once up-front
        except Exception as e:
            logging.warning("IMU serial connect failed initially: %s", e)

        self._imu_step_index = 0  # for IMU payloads

        self.qualify = qualify

    # ------------------------------- Small helpers -------------------------------

    @staticmethod
    def _u8(x) -> int:
        """
        @brief Clamp a numeric value to 0..255 and return int.
        """
        try:
            xi = int(round(float(x)))
        except Exception:
            xi = 0
        return max(0, min(255, xi))

    @staticmethod
    def _pwm_us_to_u8(us: float, lo: float = 1000.0, hi: float = 2000.0) -> int:
        """
        @brief Map a PWM in microseconds (default 1000..2000) to 0..255 (byte).
        @param us Input microseconds (may be str/float/int). Clamped to [lo..hi].
        @param lo Low end of PWM range.
        @param hi High end of PWM range.
        """
        try:
            u = float(us)
        except Exception:
            return 0
        if hi <= lo:
            return 0
        # clamp to [lo..hi]
        if u < lo: u = lo
        if u > hi: u = hi
        t = (u - lo) / (hi - lo)  # 0..1
        return HardwareInterface._u8(round(t * 255.0))

    # ------------------------------- I2C core -------------------------------

    def _sendI2CPacket(self, data: List[int], address: str) -> None:
        """
        @brief Send a byte list to an I2C 7-bit address using write_i2c_block_data.
        @param data List of integers 0..255.
        @param address Address as int or '0x..' string.
        """
        try:
            addr_int = _to_addr(address)
            # Ensure all entries are u8
            payload = [self._u8(x) for x in data]
            self.bus.write_i2c_block_data(addr_int, 0, payload)
        except Exception as e:
            logging.error("Failed to send I2C packet to %s: %s", address, e)

    # ------------------------------- I2C probing -------------------------------

    def check_hardware_addresses(self):
        """
        @brief Probe configured I2C addresses using I2C_RDWR read (adapter-friendly).
        @details
          - Skips read-probe for addresses in self._skip_probe_addrs (e.g., 0x4C RX-only motor controller).
          - Treats NACK (errno 121) as 'not present' without spamming tracebacks.
        """
        for addr in self._config_addresses():
            if addr in self._skip_probe_addrs:
                logging.info("Skipping probe for write-only/RX-only device at %s", hex(addr))
                continue

            ok, err = _probe_i2c_rdwr(self.bus, _to_addr(addr), read_len=1)
            if ok:
                logging.info("Device responded at address: %s", hex(addr))
            else:
                # If it's just a NACK, log at INFO; otherwise ERROR
                level = logging.INFO if (err and '121' in err) else logging.ERROR
                logging.log(level, "No device at %s (%s)", hex(addr), err or "no response")

    def _config_addresses(self) -> List[int]:
        """
        @brief Gather all configured I2C addresses as ints.
        """
        keys = [
            'IMU_Address',
            'Hydrophone_Address',
            'Motor_Controller_Address',
            'Blank_Address',
            'Display_Address',
            'Torpedo_Address',
            'Arm_Controller_Address',
            'Power_Safety_Address'
        ]
        addrs = []
        for k in keys:
            if k in self.config:
                try:
                    addrs.append(_to_addr(self.config[k]))
                except Exception as e:
                    logging.warning("Bad address for %s: %r (%s)", k, self.config[k], e)
        return addrs

    # ------------------------------- IMU Serial -------------------------------

    def _SerialIMU(self):
        """
        @brief Initializes/reads the IMU and updates sensor_data['IMU_Data'].
        @details
          Calls bno08x.get_data() which returns a dict with ACCEL_X/Y/Z, GYRO_X/Y/Z, MAG_X/Y/Z
          matching the database schema. Values are signed integers centered at 0.
        """
        try:
            data = None
            # Get dict with raw sensor data from BNO08x helper class
            if hasattr(self.bno08x, "get_data"):
                data = self.bno08x.get_data()  # type: ignore[attr-defined]

            if data:
                # Extract raw sensor data matching database schema
                self.sensor_data['IMU_Data']["ACCEL_X"] = float(data.get("ACCEL_X", 0.0))
                self.sensor_data['IMU_Data']["ACCEL_Y"] = float(data.get("ACCEL_Y", 0.0))
                self.sensor_data['IMU_Data']["ACCEL_Z"] = float(data.get("ACCEL_Z", 0.0))
                self.sensor_data['IMU_Data']["GYRO_X"]  = float(data.get("GYRO_X", 0.0))
                self.sensor_data['IMU_Data']["GYRO_Y"]  = float(data.get("GYRO_Y", 0.0))
                self.sensor_data['IMU_Data']["GYRO_Z"]  = float(data.get("GYRO_Z", 0.0))
                self.sensor_data['IMU_Data']["MAG_X"]   = float(data.get("MAG_X", 0.0))
                self.sensor_data['IMU_Data']["MAG_Y"]   = float(data.get("MAG_Y", 0.0))
                self.sensor_data['IMU_Data']["MAG_Z"]   = float(data.get("MAG_Z", 0.0))
                logging.info("IMU: %s", self.sensor_data['IMU_Data'])
                return

            logging.debug("IMU packet: None (timeout/invalid data)")
        except Exception as e:
            logging.error("Failed to retrieve IMU data: %s", str(e))

    # ------------------------------- Controller senders -------------------------------

    def _MotorController(self, data: dict):
        """
        @brief Sends motor control data (M1..M8) to the motor controller as bytes 0..255.
        """
        try:
            sent_data = [value for key, value in data.items() if key.startswith("M")]
            self.bus.write_i2c_block_data(76, 0, sent_data)
            # logging.error("Motor control data sent (u8): %s", sent_data)
        except Exception as e:
            logging.error("Failed to send motor control data: %s", str(e))
            return
    
    def _TorpController(self, data: dict):
        """
        @brief Sends S2/S3 to the Torpedo controller as bytes 0..255.
        @details
          If your torpedoes use 1300..1700 µs, that range is applied for mapping.
        """
        try:
            sentData = [
                self._pwm_us_to_u8(data.get("S2", 90), 90, 150),
                self._pwm_us_to_u8(data.get("S3", 90), 90, 150),
            ]
            logging.error("Torpedo control data sent (u8): %s", sentData)
            self._sendI2CPacket(sentData, hex(self.config['Torpedo_Controller_Address']))
        except Exception as e:
            logging.error("Failed to send torpedo control data: %s", str(e))

    def _ArmServoController(self, data: dict):
        """
        @brief Sends S1 to the Arm controller as a byte 0..255.
        """
        try:
            sentData = [self._pwm_us_to_u8(data.get("S1", 127))]
            self._sendI2CPacket(sentData, hex(self.config['Arm_Controller_Address']))
            logging.error("Arm control data sent (u8): %s", sentData)
        except Exception as e:
            logging.error("Failed to send arm control data: %s", str(e))

    # ------------------------------- Processes -------------------------------

    def ControlProcess(self):
        """
        @brief Loop fetching latest outputs from DB and forwarding to controllers.
        @details
          Pulls /outputs/latest (dict) to avoid list handling. Applies defaults if fields missing.
        """
        url = f"{self.config['DB_Address']}:{self.config['DB_Port']}/outputs/latest"
        try:
            row = getDataFromServer(url)  # dict or None/null
            if not isinstance(row, dict):
                # nothing available yet
                time.sleep(0.02)
                logging.error("ControlProcess no data available")
                pass
            else:
                logging.error(f"ControlProcess Raw Data: {row}")

                # Build slices with safe defaults (DB stores µs floats/ints)
                motors = {k: int(row.get(k, 127)) for k in ("M1","M2","M3","M4","M5","M6","M7","M8")}
                torp   = {"S2": int(row.get("S2", 127)), "S3": int(row.get("S3", 127))}
                arm    = {"S1": int(row.get("S1", 127))}

                logging.error(f"ControlProcess Split Data: {motors}, {torp}, {arm}")

                self._MotorController(motors)
                # self._TorpController(torp)
                # self._ArmServoController(arm)
        except Exception as e:
            logging.error("ControlProcess error: %s", e)

    def SensorProcess(self):
        """
        @brief Loop fetching IMU packet from serial and pushing to DB.
        """
        try:
            self._SerialIMU()
            imu_raw = self.sensor_data['IMU_Data']
            imu_payload = self._format_imu_payload(imu_raw)

            sendDataToServer(
                imu_payload,
                f"{self.config['DB_Address']}:{self.config['DB_Port']}/imu/"
            )
        except Exception as e:
            logging.error("SensorProcess error: %s", e)

    def _format_imu_payload(self, imu_raw: dict) -> dict:
        """
        @brief Normalize raw IMU dictionary to API schema.
        @param imu_raw Raw IMU dict. May contain capitalized keys like 'Roll'.
        @return Dict matching the /imu/ POST schema.

        Expected schema:
          step_index: int
          X, Y, Z: float
          roll, pitch, yaw: float  (lowercase)
        
        New Schema accel x, accel y, accel z, gyro [x,y,z], mag[x,y,z]
        """
        # Extract with safe defaults; cast to float
        X = float(imu_raw.get('X', 0.0))
        Y = float(imu_raw.get('Y', 0.0))
        Z = float(imu_raw.get('Z', 0.0))

        # Accept either lowercase or capitalized keys from the sensor layer
        roll  = float(imu_raw.get('roll',  imu_raw.get('Roll',  0.0)))
        pitch = float(imu_raw.get('pitch', imu_raw.get('Pitch', 0.0)))
        yaw   = float(imu_raw.get('yaw',   imu_raw.get('Yaw',   0.0)))

        payload = {
            "ACCEL_X": float(imu_raw.get('ACCEL_X', 0.0)),
            "ACCEL_Y": float(imu_raw.get('ACCEL_Y', 0.0)),
            "ACCEL_Z": float(imu_raw.get('ACCEL_Z', 0.0)),
            "GYRO_X":  float(imu_raw.get('GYRO_X', 0.0)),
            "GYRO_Y":  float(imu_raw.get('GYRO_Y', 0.0)),
            "GYRO_Z":  float(imu_raw.get('GYRO_Z', 0.0)),
            "MAG_X":   float(imu_raw.get('MAG_X', 0.0)),
            "MAG_Y":   float(imu_raw.get('MAG_Y', 0.0)),
            "MAG_Z":   float(imu_raw.get('MAG_Z', 0.0))
        }
        return payload


    def run(self):
        """
        @brief Start control and sensor processes and wait (join).
        """
        # Optional one more probe at runtime start
        self.check_hardware_addresses()

        # control_proc = multiprocessing.Process(target=self.ControlProcess, daemon=True)
        # sensor_proc  = multiprocessing.Process(target=self.SensorProcess,  daemon=True)
        # control_proc.start()
        # sensor_proc.start()
        # control_proc.join()
        # sensor_proc.join()

        while True:
        # # #     if not self.qualify:
            self.ControlProcess()
        # self.qualification()
            #     # self.SensorProcess()
            #     time.sleep(0.02)  # ~50 Hz
            # else:
            #     # self.SensorProcess()
            #     time.sleep(0.02)  # ~50 Hz

    # ------------------------------- TODO modules -------------------------------

    def _Blank(self):           pass
    def _Display(self):         pass
    def _Torpedo(self):         pass
    def _ArmController(self):   pass
    def _PowerSafety(self):     pass
    def _Hydrophone(self):      pass
    def _I2CIMU(self):          pass


def run(qualify : bool = False):
    """
    @brief Entrypoint to launch the hardware interface.
    @param qualify: Whether to run in qualification mode.
    """
    hardware_interface = HardwareInterface(qualify=qualify)
    hardware_interface.run()