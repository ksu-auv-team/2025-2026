import argparse
import sys
import time

import pygame
import requests

from libs.config import get_env
from shared.mapping import map_range


class Controller:
    def __init__(self, lr: bool = False, debug: bool = True, send_db: bool = False):
        """
        @brief Initialize joystick controller and internal state.
        @param lr Last-resort mode flag (unused in normal parse path).
        @param debug Enable console debug output.
        @param send_db Enable sending data to the database.
        """
        self.joystick = None
        self.lr = lr  # last_resort
        self.debug = debug
        self.send_db = send_db

        pygame.init()

        while not self.joystick:
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                self.joystick = pygame.joystick.Joystick(0)
                self.joystick.init()
            else:
                print("No joystick found. Please connect a joystick.")

        self.joy_data = []
        self.deadzone = 0.1

        self.orin_ip = get_env("ORIN_IP", default="192.168.72.75")
        self.orin_port = get_env("ORIN_PORT", default="5000")

        # Output payload. Note: X/Y/Z/Yaw set to 0 when in deadzone; adjust as needed.
        self.out_data = {
            "arm": False,   # Always treated as boolean in logic
            "x": 0,
            "y": 0,
            "z": 0,
            "yaw": 0,
            "s1": 0,
            "s2": 0,
            "s3": 0,
            "step_index": 0,
        }

        # --- Edge detection / one-shot reset control ---
        self.prev_arm = False     # Arm value from previous loop
        self.has_armed = False    # Has Arm ever been True since start?
        self.reset_fired = False  # Has the post-arm falling-edge reset fired?

    def gather_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                quit()

        self.joystick.init()

        self.joy_data = [round(self.joystick.get_axis(i), 2) for i in range(self.joystick.get_numaxes())]  # type: ignore
        for i in range(self.joystick.get_numbuttons()):  # type: ignore
            self.joy_data.append(self.joystick.get_button(i))  # type: ignore
        for i in range(self.joystick.get_numhats()):  # type: ignore
            self.joy_data.append(self.joystick.get_hat(i))  # type: ignore

    def parse(self):
        """
        @brief Parse joystick axes/buttons into out_data fields.
        @details
          - Maps axes into X/Y/Z/Yaw with deadzone clipping.
          - Interprets Arm as a boolean (True when pressed/active beyond deadzone).
        @note Adjust axis indices and ranges as needed for your hardware.
        """
        if not self.lr:
            # Arm: treat as boolean. If button index 19 is used and returns 0/1,
            # this yields True when pressed, else False. If it's an axis, deadzone applies.
            #arm_raw = self.joy_data[19] if len(self.joy_data) > 19 else 0

            arm_in = self.joy_data[10] #right bumper

            if arm_in != 0:
                self.out_data["arm"] = True
            else:
                self.out_data["arm"] = False
            
            #self.out_data["arm"] = bool(arm_raw if abs(arm_raw) > self.deadzone else 0)

            if self.out_data["arm"]:
                self.out_data["step_index"] += 1
            else:
                self.out_data["step_index"] = 0

            # Axes → [-1, 1] (or 0 if within deadzone)
            self.out_data["x"] = map_range(x=self.joy_data[4], in_max=0.88, in_min=-0.91, out_min=-1, out_max=1) if abs(self.joy_data[4]) > self.deadzone else 0
            self.out_data["y"] = map_range(x=self.joy_data[3], in_max=0.83, in_min=-0.85, out_min=-1, out_max=1) if abs(self.joy_data[3]) > self.deadzone else 0
            self.out_data["z"] = map_range(x=self.joy_data[1], in_max=0.55, in_min=-0.82, out_min=-1, out_max=1) if abs(self.joy_data[1]) > self.deadzone else 0
            self.out_data["yaw"] = map_range(x=self.joy_data[0], in_max=0.86, in_min=-0.78, out_min=-1, out_max=1) if abs(self.joy_data[0]) > self.deadzone else 0
        else:
            # Last-resort mode path (if used elsewhere)
            pass

    def send_to_db(self):
        """
        @brief Send current out_data to the database.
        @details Sends to /inputs or /outputs based on last-resort flag.
        """
        base_url = f"http://{self.orin_ip}:{self.orin_port}"
        if not self.lr:
            self.response = requests.post(f"{base_url}/inputs/", json=self.out_data)
        else:
            self.response = requests.post(f"{base_url}/outputs/", json=self.out_data)
        if self.response.status_code == 200:
            print("Data sent successfully")
        else:
            print("Failed to send data")

    def debug_output(self):
        """
        @brief Print joystick and output data in a scrolling-friendly way.
        """
        length_joy_data = len(self.joy_data)
        out_string = ""
        out_string += f"Last Resort: {self.lr}\n"
        for i in range(length_joy_data):
            out_string += f"Joy Data[{i}]: {self.joy_data[i]}, "
            if i % 5 == 0 and i != 0:
                out_string += "\n"
        out_string += f"Out Data: {self.out_data}\n"
        out_string += f"Sent: {self.sent}\n"
        # Move cursor to top-left and clear screen
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.write(out_string)
        sys.stdout.flush()

    def reset_out_data(self):
        """
        @brief Reset out_data to default values and send once to DB.
        @details This is intended to run once on the first falling edge after Arm has been True.
        """
        self.out_data = {
            "arm": False,
            "x": 127,
            "y": 127,
            "z": 127,
            "yaw": 127,
            "step_index": 0,
            "s1": 0,
            "s2": 0,
            "s3": 0,
        }
        self.send_to_db()

    def run(self):
        """
        @brief Main input/parse/send loop with edge detection for one-shot reset.
        @details
          - Rising edge (False->True): marks that Arm has been active.
          - Falling edge (True->False): if Arm was previously active and reset not fired,
            call reset_out_data() exactly once.
        """
        while True:
            self.gather_input()
            self.parse()

            current_arm = bool(self.out_data["arm"])

            # Rising edge: mark that Arm has been True at least once and allow a future reset.
            if current_arm and not self.prev_arm:
                self.has_armed = True
                # Allow a future reset on the next falling edge
                self.reset_fired = False

            # Falling edge: fire reset exactly once if Arm had been True before.
            if (not current_arm) and self.prev_arm and self.has_armed and (not self.reset_fired):
                if self.send_db:
                    self.reset_out_data()
                self.reset_fired = True
                # Optional: break after reset (matches your original behavior).
                # Remove this break if you want the loop to continue running after the one-shot reset.
                break

            self.sent = 0
            # Only send continuous data while armed; falling-edge block above handles reset+break.
            if self.send_db and current_arm:
                self.send_to_db()
                self.sent = 1

            if self.debug:
                self.debug_output()

            # Update previous value for next loop iteration
            self.prev_arm = current_arm


            time.sleep(0.01)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Controller for joystick input")
    parser.add_argument("--lr", action="store_true", help="Enable last resort mode")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--send-db", dest="send_db", action="store_true", help="Enable sending data to database")
    args = parser.parse_args()

    con = Controller(lr=args.lr, debug=args.debug, send_db=args.send_db)
    con.run()