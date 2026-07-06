import argparse
import sys
import time

import pygame

from libs.config import get_env
from libs.quick_request import AUVClient
from shared.mapping import map_range

# --- Joystick axis calibration ------------------------------------------
# Axis indices/ranges are controller-specific. Run with --debug to print
# raw axis values and adjust these to match your hardware.
AXIS_SURGE = 4
AXIS_SWAY = 3
AXIS_HEAVE = 1
AXIS_YAW = 0

AXIS_RANGES = {
    AXIS_SURGE: (-0.91, 0.88),
    AXIS_SWAY: (-0.85, 0.83),
    AXIS_HEAVE: (-0.82, 0.55),
    AXIS_YAW: (-0.78, 0.86),
}

DEADZONE = 0.1
NEUTRAL = 0.0


class Controller:
    def __init__(self, debug: bool = False, send: bool = False) -> None:
        self.debug = debug
        self.send = send
        self.axes: list[float] = []
        self.buttons: list[int] = []

        pygame.init()
        pygame.joystick.init()
        self.joystick = self._connect_joystick()

        host = get_env("ORIN_IP", default="192.168.8.138")
        port = get_env("AUV_PORT", default="8000")
        self.client = AUVClient(f"http://{host}:{port}")

    def _connect_joystick(self):
        while pygame.joystick.get_count() == 0:
            print("No joystick found. Please connect a joystick.")
            time.sleep(1)
            pygame.joystick.quit()
            pygame.joystick.init()
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        return joystick

    def gather_input(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit

        self.axes = [round(self.joystick.get_axis(i), 2) for i in range(self.joystick.get_numaxes())]
        self.buttons = [self.joystick.get_button(i) for i in range(self.joystick.get_numbuttons())]

    def _axis_normalized(self, index: int) -> float:
        value = self.axes[index] if index < len(self.axes) else 0.0
        if abs(value) <= DEADZONE:
            return NEUTRAL
        in_min, in_max = AXIS_RANGES[index]
        return map_range(x=value, in_min=in_min, in_max=in_max, out_min=-1, out_max=1)

    def parse(self) -> dict:
        return {
            "SURGE": self._axis_normalized(AXIS_SURGE),
            "SWAY": self._axis_normalized(AXIS_SWAY),
            "HEAVE": self._axis_normalized(AXIS_HEAVE),
            "ROLL": NEUTRAL,
            "PITCH": NEUTRAL,
            "YAW": self._axis_normalized(AXIS_YAW),
            "S1": 0,
            "S2": 0,
            "S3": 0,
            "ARM": 1,  # armed for the lifetime of the process
        }

    def debug_output(self, out_data: dict) -> None:
        lines = [
            f"Axes:    {self.axes}",
            f"Buttons: {self.buttons}",
            f"Out:     {out_data}",
        ]
        sys.stdout.write("\033[2J\033[H" + "\n".join(lines) + "\n")
        sys.stdout.flush()

    def run(self) -> None:
        while True:
            self.gather_input()
            out_data = self.parse()

            if self.send:
                self.client.post("inputs", **out_data)

            if self.debug:
                self.debug_output(out_data)

            time.sleep(0.01)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Joystick controller for AUV input")
    parser.add_argument("--debug", action="store_true", help="Print raw axis/button values and parsed output")
    parser.add_argument("--send", action="store_true", help="Send parsed input to the AUV database")
    args = parser.parse_args()

    Controller(debug=args.debug, send=args.send).run()
