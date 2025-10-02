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
        self.config: Dict[str, Any] = load_config('config/hardware_config.json')

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
            "IMU_Data": {"X": 0.0, "Y": 0.0, "Z": 0.0, "Roll": 0.0, "Pitch": 0.0, "Yaw": 0.0},
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

    def qualification(self):
        starting_delay = 5
        initial_movemnet = 4
        reverse_hold = 1
        down_hold = 3
        second_movement = 4
        up_movement = 5
        time.sleep(starting_delay)
        breakCase = time.time() + initial_movemnet*1
        while True:
            motors: Dict[str, int] = {
                "M1": int(255), "M2": int(255), "M3": int(0), "M4": int(255),
                "M5": int(255), "M6": int(255), "M7": int(0), "M8": int(0)
            }
            self._MotorController(motors)
            if (time.time() > breakCase):
                break
        motors: Dict[str, int] = {
            "M1": int(127), "M2": int(127), "M3": int(127), "M4": int(127),
            "M5": int(255), "M6": int(255), "M7": int(0), "M8": int(0)
        }
        self._MotorController(motors)
        time.sleep(2)
        breakCase = time.time() + reverse_hold*1
        while True:
            motors: Dict[str, int] = {
                "M1": int(0), "M2": int(0), "M3": int(255), "M4": int(0),
                "M5": int(255), "M6": int(255), "M7": int(0), "M8": int(0)
            }
            self._MotorController(motors)
            if (time.time() > breakCase):
                break
        motors: Dict[str, int] = {
            "M1": int(127), "M2": int(127), "M3": int(127), "M4": int(127),
            "M5": int(127), "M6": int(127), "M7": int(127), "M8": int(127)
        }
        self._MotorController(motors)
        time.sleep(2)
        breakCase = time.time() + down_hold*1
        while True:
            motors: Dict[str, int] = {
                "M1": int(127), "M2": int(127), "M3": int(127), "M4": int(127),
                "M5": int(0), "M6": int(0), "M7": int(255), "M8": int(255)
            }
            self._MotorController(motors)
            if time.time() > breakCase:
                break
        breakCase = time.time() + second_movement*1
        while True:
            motors: Dict[str, int] = {
                "M1": int(255), "M2": int(255), "M3": int(0), "M4": int(255),
                "M5": int(127), "M6": int(127), "M7": int(127), "M8": int(127)
            }
            self._MotorController(motors)
            if time.time() > breakCase:
                break
        breakCase = time.time() + up_movement*1
        while True:
            motors: Dict[str, int] = {
                "M1": int(127), "M2": int(127), "M3": int(127), "M4": int(127),
                "M5": int(255), "M6": int(255), "M7": int(0), "M8": int(0)
            }
            self._MotorController(motors)
            if time.time() > breakCase:
                break

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

    def _config_addresses(self):
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
          Prefers BNO08x.get_data() (dict) if available.
          Falls back to get_data_json_str() or a raw "{x,y,z,r,p,y}" line if necessary.
        """
        try:
            data = None
            # Preferred: dict with engineering units from our helper class
            if hasattr(self.bno08x, "get_data"):
                data = self.bno08x.get_data()  # type: ignore[attr-defined]

            if data:
                vel = data.get("vel_ms", {})
                ang = data.get("euler_deg", {})
                self.sensor_data['IMU_Data']["X"]     = float(vel.get("X_vel", 0.0))
                self.sensor_data['IMU_Data']["Y"]     = float(vel.get("Y_vel", 0.0))
                self.sensor_data['IMU_Data']["Z"]     = float(vel.get("Z_vel", 0.0))
                self.sensor_data['IMU_Data']["Roll"]  = float(ang.get("Roll", 0.0))
                self.sensor_data['IMU_Data']["Pitch"] = float(ang.get("Pitch", 0.0))
                self.sensor_data['IMU_Data']["Yaw"]   = float(ang.get("Yaw", 0.0))
                logging.info("IMU: %s", self.sensor_data['IMU_Data'])
                return

            # Fallback: JSON string produced by helper
            if hasattr(self.bno08x, "get_data_json_str"):
                s = self.bno08x.get_data_json_str()  # type: ignore[attr-defined]
                if s:
                    try:
                        obj = json.loads(s)
                        vel = obj.get("vel_ms", {})
                        ang = obj.get("euler_deg", {})
                        self.sensor_data['IMU_Data']["X"]     = float(vel.get("X_vel", 0.0))
                        self.sensor_data['IMU_Data']["Y"]     = float(vel.get("Y_vel", 0.0))
                        self.sensor_data['IMU_Data']["Z"]     = float(vel.get("Z_vel", 0.0))
                        self.sensor_data['IMU_Data']["Roll"]  = float(ang.get("Roll", 0.0))
                        self.sensor_data['IMU_Data']["Pitch"] = float(ang.get("Pitch", 0.0))
                        self.sensor_data['IMU_Data']["Yaw"]   = float(ang.get("Yaw", 0.0))
                        logging.info("IMU: %s", self.sensor_data['IMU_Data'])
                        return
                    except Exception:
                        pass

            # Last-resort fallback: a raw "{vx,vy,vz,roll,pitch,yaw}" line of 0..256 ints
            if hasattr(self.bno08x, "serial") and self.bno08x.serial and self.bno08x.serial.is_open:
                line = self.bno08x.serial.readline().decode("utf-8", errors="ignore").strip()
                if line.startswith("{") and line.endswith("}"):
                    parts = [p.strip() for p in line[1:-1].split(",")]
                    if len(parts) == 6:
                        vals = [max(0, min(256, int(p))) for p in parts]
                        # Map back to engineering units:
                        # - Velocities assume MCU mapped [-VEL_MAX, +VEL_MAX] -> [0..256]; default VEL_MAX=2.0
                        # - Angles assume MCU mapped [-180..180] -> [0..256]
                        VEL_MAX = getattr(self.bno08x, "VEL_MAX_MPS", 2.0)
                        def u256_to_vel(u): return (float(u)/256.0) * (2.0*VEL_MAX) - VEL_MAX
                        def u256_to_deg(u): return (float(u)/256.0) * 360.0 - 180.0

                        self.sensor_data['IMU_Data']["X"]     = u256_to_vel(vals[0])
                        self.sensor_data['IMU_Data']["Y"]     = u256_to_vel(vals[1])
                        self.sensor_data['IMU_Data']["Z"]     = u256_to_vel(vals[2])
                        self.sensor_data['IMU_Data']["Roll"]  = u256_to_deg(vals[3])
                        self.sensor_data['IMU_Data']["Pitch"] = u256_to_deg(vals[4])
                        self.sensor_data['IMU_Data']["Yaw"]   = u256_to_deg(vals[5])

                        logging.info("IMU (fallback): %s", self.sensor_data['IMU_Data'])
                        return

            logging.debug("IMU packet: None (timeout/invalid line)")
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
            "step_index": int(self._imu_step_index + 1),
            "X": X, "Y": Y, "Z": Z,
            "roll": roll, "pitch": pitch, "yaw": yaw
        }

        # Increment after use
        self._imu_step_index += 1
        return payload

    # ------------------------------- Runner -------------------------------

    def _find_last_true_segment_between_falses(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        @brief Return the newest contiguous slice of rows that is strictly
               between arm == False and arm == False and contains at least one True.
        @details Example arm timeline:
                 F, T, T, F, F, T, T, T, F
                 -> returns rows[5:8] (indices 5..7), because it's the last segment
                    bounded by False on both sides and containing True(s).
        """
        if not rows:
            return []

        # Ensure deterministic order (db_utils.list_outputs() already orders by step_index)
        rows = sorted(rows, key=lambda r: r.get("step_index", r.get("id", 0)))
        arms = [bool(r.get("arm", False) or r.get("Arm", False)) for r in rows]

        false_idxs = [i for i, a in enumerate(arms) if not a]
        if len(false_idxs) < 2:
            return []  # need at least False .. False to bound a segment

        # Walk *consecutive* pairs of False indices from the end to the start
        for j in range(len(false_idxs) - 1, 0, -1):
            f0 = false_idxs[j - 1]
            f1 = false_idxs[j]
            if f1 - f0 <= 1:
                # consecutive falses -> empty window, skip
                continue
            # If there's at least one True between f0 and f1, that's a valid segment
            if any(arms[i] for i in range(f0 + 1, f1)):
                return rows[f0 + 1 : f1]

        return []  # no complete bounded True segment found

    # -------------------------------------------------------------------------
    # Data loading + storing for replay
    # -------------------------------------------------------------------------
    def replay(self) -> int:
        """
        @brief Fetch all outputs, locate the newest arm==True segment bounded by
               arm==False on both sides, and store it for playback.
        @return Number of frames stored in _replay_frames.
        """
        url = f"{self.config['DB_Address']}:{self.config['DB_Port']}/outputs/"
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                logging.warning("replay(): unexpected response (not a list): %r", type(rows))
                self._replay_frames = []
                self._replay_cursor = 0
                return 0

            segment = self._find_last_true_segment_between_falses(rows)
            self._replay_frames: List[Dict[str, Any]] = segment
            self._replay_cursor: int = 0

            if not segment:
                logging.info("replay(): no complete arm==True segment found between False boundaries.")
                return 0

            start_idx = segment[0].get("step_index")
            end_idx   = segment[-1].get("step_index")
            logging.info(
                "replay(): stored %d frames (step_index %s..%s) for playback.",
                len(segment), start_idx, end_idx
            )
            return len(segment)

        except Exception as e:
            logging.error("replay() failed: %s", e)
            self._replay_frames = []
            self._replay_cursor = 0
            return 0

    # -------------------------------------------------------------------------
    # Optional: play the stored replay segment to hardware at a fixed rate
    # -------------------------------------------------------------------------
    def play_replay(self, rate_hz: float = 50.0) -> None:
        """
        @brief Drive the motors through the stored replay frames at a fixed rate.
        @details Call replay() first. This will send only M1..M8 (like ControlProcess).
        """
        frames: List[Dict[str, Any]] = getattr(self, "_replay_frames", [])
        if not frames:
            logging.warning("play_replay(): no frames loaded; call replay() first.")
            return

        period = 1.0 / max(rate_hz, 1.0)
        NEUTRAL = {k: 127 for k in ("M1","M2","M3","M4","M5","M6","M7","M8")}

        try:
            for frame in frames:
                motors = {k: int(frame.get(k, 127)) for k in ("M1","M2","M3","M4","M5","M6","M7","M8")}
                self._MotorController(motors)
                time.sleep(period)
        except Exception as e:
            logging.error("play_replay() error: %s", e)
        finally:
            # Always neutralize at the end
            self._MotorController(NEUTRAL)

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