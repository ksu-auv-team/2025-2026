"""
Motor sweep test — sends values directly to the ESCs over I2C, no database.

Sweep profile (all motors move together):
  neutral (127) → peak_high → neutral → peak_low → neutral

Usage:
  python motor_sweep_test.py
  python motor_sweep_test.py --peak-high 160 --peak-low 95 --step-delay 0.02
  python motor_sweep_test.py --motors 0 1   # only sweep M1 and M2 (0-indexed)
"""

import argparse
import time

import smbus2

from libs.hardware_interface.modules.motors import (
    I2C_ADDRESS,
    I2C_BUS,
    DEFAULT_PWM,
    send_motor_values,
)

MOTOR_NAMES = ["M1", "M2", "M3", "M4", "VERT"]


def _build_frame(base: list[int], active: list[int], value: int) -> list[int]:
    """Return a 5-value frame with `value` applied to active motor indices, neutral elsewhere."""
    frame = base[:]
    for i in active:
        frame[i] = value
    return frame


def sweep(
    bus: smbus2.SMBus,
    active_motors: list[int],
    peak_high: int,
    peak_low: int,
    step: int,
    step_delay: float,
) -> None:
    base = [DEFAULT_PWM] * 5

    def ramp(start: int, end: int) -> None:
        direction = 1 if end > start else -1
        for val in range(start, end + direction, direction * step):
            val = max(0, min(255, val))
            frame = _build_frame(base, active_motors, val)
            send_motor_values(bus, frame)
            names = ", ".join(MOTOR_NAMES[i] for i in active_motors)
            print(f"  [{names}] = {val}")
            time.sleep(step_delay)

    print(f"Neutral ({DEFAULT_PWM}) → High ({peak_high})")
    ramp(DEFAULT_PWM, peak_high)

    print(f"High ({peak_high}) → Neutral ({DEFAULT_PWM})")
    ramp(peak_high, DEFAULT_PWM)

    print(f"Neutral ({DEFAULT_PWM}) → Low ({peak_low})")
    ramp(DEFAULT_PWM, peak_low)

    print(f"Low ({peak_low}) → Neutral ({DEFAULT_PWM})")
    ramp(peak_low, DEFAULT_PWM)


def main() -> None:
    parser = argparse.ArgumentParser(description="Motor ESC sweep test")
    parser.add_argument("--bus",        type=int,   default=I2C_BUS,    help="I2C bus number (default: %(default)s)")
    parser.add_argument("--peak-high",  type=int,   default=180,        help="Upper sweep limit 0-255 (default: %(default)s)")
    parser.add_argument("--peak-low",   type=int,   default=75,         help="Lower sweep limit 0-255 (default: %(default)s)")
    parser.add_argument("--step",       type=int,   default=1,          help="Value increment per tick (default: %(default)s)")
    parser.add_argument("--step-delay", type=float, default=0.05,       help="Seconds between steps (default: %(default)s)")
    parser.add_argument("--motors",     type=int,   nargs="+",          help="Motor indices to sweep 0-4 (default: all)")
    args = parser.parse_args()

    active = args.motors if args.motors is not None else list(range(5))
    invalid = [i for i in active if not 0 <= i <= 4]
    if invalid:
        parser.error(f"Invalid motor indices: {invalid}. Must be 0-4.")

    print(f"Connecting to I2C bus {args.bus}, address 0x{I2C_ADDRESS:02X}...")
    try:
        with smbus2.SMBus(args.bus) as bus:
            neutral = [DEFAULT_PWM] * 5
            if not send_motor_values(bus, neutral):
                print("Failed to reach Arduino. Is it connected?")
                return

            print(f"Arduino connected. Starting sweep on motors: {[MOTOR_NAMES[i] for i in active]}")
            print(f"  Range: {args.peak_low} ← {DEFAULT_PWM} → {args.peak_high}  |  step={args.step}  delay={args.step_delay}s")
            print("Press Ctrl+C to stop.\n")

            sweep(bus, active, args.peak_high, args.peak_low, args.step, args.step_delay)
            print("\nSweep complete.")

    except KeyboardInterrupt:
        print("\nInterrupted — sending neutral before exit.")
        with smbus2.SMBus(args.bus) as bus:
            send_motor_values(bus, [DEFAULT_PWM] * 5)
        print("Done.")


if __name__ == "__main__":
    main()
