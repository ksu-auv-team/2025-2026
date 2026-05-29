from .logic import fetch_data, post_data, get_latest_data
from .config_loader import load_config
from .pid import PIDController

import logging
from typing import Dict, List, Union

import requests


def map(x: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    """
    @brief Map a value from one range to another.
    """
    return round((x - in_min) / (in_max - in_min) * (out_max - out_min) + out_min, 2)


class MovementPackage:
    """
    @class MovementPackage
    @brief Pulls latest inputs, computes thruster outputs via PID, and updates DB.
    @details
      - Keeps control values in normalized space [-1, 1] for stability/testing.
      - Exposes PID like a list: list(self.PID) -> [M1..M8].
      - Optionally scales M* / S* to 0–255 right before posting if config['ScaleToU8'] is True.
      - Output payload strictly matches Outputs schema: step_index, M1..M8, S1..S3, arm.
    """

    def __init__(self, package_name: str = "movement_package"):
        """
        @brief Initialize with config, logger, and PID controller.
        @param package_name Name used to load config.
        """
        self.package_name = package_name
        self.config = load_config(package_name)
        self.logger = logging.getLogger(package_name)

        # Latest parsed inputs (normalized space; matches corrected input schema)
        self.parsed_inputs = {
            "id": 0,
            "step_index": 0,
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "yaw": 0.0,
            "s1": 0.0,
            "s2": 0.0,
            "s3": 0.0,
            "arm": False
        }

        # Combined output payload; keep floats in [-1,1] by default; no extra fields beyond schema.
        self.combined_output: Dict[str, Union[int, float, bool]] = {
            "step_index": 0,
            "M1": int(127), "M2": int(127), "M3": int(127), "M4": int(127),
            "M5": int(127), "M6": int(127), "M7": int(127), "M8": int(127),
            "S1": int(127), "S2": int(127), "S3": int(127),
            "arm": False
        }
        self.logger.info("Combined output initialized: %s", self.combined_output)

        # PID with list-like interface (see pid.py)
        self.PID = PIDController()

        # Reload config in case it changed externally
        self.config = load_config(self.package_name)

    def _pid_flat(self) -> List[float]:
        """
        @brief Get motors M1..M8 from PID as a flat list.
        @return [M1..M8] floats in normalized space.
        """
        try:
            return list(self.PID)  # relies on PID.__iter__()
        except TypeError:
            return [*self.PID.horizontal_motors.tolist(), *self.PID.vertical_motors.tolist()]

    def _scale_to_u8(self, val: float) -> int:
        """
        @brief Scale a normalized value [-1,1] to unsigned 8-bit [0,255].
        """
        v = max(-1.0, min(1.0, float(val)))
        return int(round(map(v, -1.0, 1.0, 0.0, 255.0)))

    def _apply_optional_scaling(self, payload: Dict[str, Union[int, float, bool]]) -> Dict[str, Union[int, float, bool]]:
        """
        @brief Optionally scale M1..M8 and S1..S3 to 0–255 for hardware/DB.
        @details Controlled by config['ScaleToU8'] (bool). Default False.
        @note 'arm' and 'step_index' are left untouched.
        """
        if not self.config.get("ScaleToU8", False):
            return payload  # leave as normalized floats

        scaled = dict(payload)
        for k in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "S1", "S2", "S3"):
            scaled[k] = self._scale_to_u8(payload[k])  # type: ignore[index]
        return scaled

    def _sanity_check_ranges(self) -> None:
        """
        @brief Log a warning if any motor leaves the normalized range.
        @details Check is done on the unscaled combined_output.
        """
        motors = [self.combined_output[k] for k in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")]
        if any(abs(float(v)) > 1.0001 for v in motors):  # type: ignore[arg-type]
            self.logger.warning("Motor value outside [-1,1]: %s", motors)

    def _parse_outputs(self) -> Dict[str, Union[int, float, bool]]:
        """
        @brief Generate output data scaled to 0-255 based on DB inputs and Mixing Matrix.
        @return The scaled output dict matching the exact Outputs database schema.
        """
        if not self.parsed_inputs:
            self.logger.warning("No parsed inputs available.")
            return self.combined_output

        if bool(self.parsed_inputs.get("Arm", False)):
            
            # Translate inputs from DB space (0 to 100) to local normalized space (-1.0 to 1.0)
            norm_x   = map(float(self.parsed_inputs.get("X", 50)), 0, 100, -1.0, 1.0)
            norm_y   = map(float(self.parsed_inputs.get("Y", 50)), 0, 100, -1.0, 1.0)
            norm_z   = map(float(self.parsed_inputs.get("Z", 50)), 0, 100, -1.0, 1.0)
            norm_yaw = map(float(self.parsed_inputs.get("Yaw", 50)), 0, 100, -1.0, 1.0)

            #Pass normalized values to surface PID tracking if needed
            self.PID.update_motors(x=norm_x, y=norm_y, z=norm_z, yaw=norm_yaw)

            # Matrix multiplication
            control_vector = np.array([norm_x, norm_y, norm_z, norm_yaw])
            mixed_outputs = np.dot(self.mixing_matrix, control_vector)
            clamped_outputs = np.clip(mixed_outputs, -1.0, 1.0)

            # Map the servo states to 0-255 outputs
            s1_out = 255 if self.parsed_inputs.get("S1", False) else 0
            s2_out = 255 if self.parsed_inputs.get("S2", False) else 0
            s3_out = int(map(float(self.parsed_inputs.get("S3", 50)), 0, 100, 0, 255))

            # Output to match the DB manager
            self.combined_output = {
                "M1": self._scale_to_u8(clamped_outputs[0]),
                "M2": self._scale_to_u8(clamped_outputs[1]),
                "M3": self._scale_to_u8(clamped_outputs[2]),
                "M4": self._scale_to_u8(clamped_outputs[3]),
                "V":  self._scale_to_u8(clamped_outputs[4]),  # Combined vertical path
                "S1": s1_out,
                "S2": s2_out,
                "S3": s3_out
            }

        else:
            # Disarmed state
            self.combined_output = {
                "M1": 127, "M2": 127, "M3": 127, "M4": 127, "V": 127,
                "S1": 0, "S2": 0, "S3": 127
            }

        return self.combined_output

    def _updateDB(self) -> None:
        """
        @brief POST the output payload to the /outputs/ endpoint.
        @details Matches OutputSchema exactly: step_index, M1..M8, S1..S3, arm.
        """
        if not self.combined_output:
            self.logger.warning("No data to update in the database.")
            return

        api_url = f"{self.config['DB_Address']}:{self.config['DB_Port']}/outputs/"
        payload = self._apply_optional_scaling(self.combined_output)
        response = post_data(api_url, payload)
        if 'error' in response:
            self.logger.error("Failed to update database: %s", response['error'])
        else:
            self.logger.info("Database updated successfully.")

    def run(self) -> None:
        """
        @brief Main loop: fetch latest inputs, compute outputs, and update DB.
        """
        # Make sure the database has arm as false for the latest input:
        response = requests.post(f"{self.config['DB_Address']}:{self.config['DB_Port']}/inputs/latest", json=self.parsed_inputs)

        while True:
            self.logger.info("Fetching latest inputs...")
            data = get_latest_data(f"{self.config['DB_Address']}:{self.config['DB_Port']}/inputs/latest")

            if data:
                self.parsed_inputs = data
                self.logger.info("Parsed inputs: %s", self.parsed_inputs)

                unscaled = self._parse_outputs()
                self.logger.info("Unscaled outputs (schema-conformant): %s", unscaled)

                self.logger.info("Updating database...")
                self._updateDB()
            else:
                self.logger.warning("No data received.")

    def test_run(self) -> None:
        """
        @brief Simple dry run for local verification (no network).
        """
        print("Running tests...")

        # Use corrected (lowercase) input keys; arm True to produce non-zero outputs
        self.parsed_inputs.update({
            "id": 1,
            "step_index": 10,
            "x": 0.0, "y": 1.0, "z": 0.0, "yaw": 0.0,
            "s1": 0.0, "s2": 0.0, "s3": 0.0,
            "arm": True
        })

        print("Inputs:", self.parsed_inputs)
        outputs = self._parse_outputs()
        print("Unscaled Outputs (will match OutputSchema keys):", outputs)
        print("Tests completed.")


def run() -> None:
    """
    @brief Entrypoint for module execution.
    """
    movement_package = MovementPackage()
    movement_package.run()
    # movement_package.test_run()

