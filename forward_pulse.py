#!/usr/bin/env python3
"""
forward_pulse.py
~~~~~~~~~~~~~~~~~
Sends a forward-surge command to the AUV's /inputs endpoint for 10 seconds,
then returns to neutral (disarmed, zeroed) thrust.

Posts repeatedly (not just once) while "moving" so the command doesn't go
stale if movement_package.py's polling loop picks up an old row.

Usage:
    python3 forward_pulse.py
    python3 forward_pulse.py --host 192.168.8.138 --port 8000
    python3 forward_pulse.py --surge 0.3 --duration 5
"""

# for quals, run: python3 forward_pulse.py --host 192.168.72.75 --surge 0.5 --heave -0.15 --duration 10

import argparse
import time

import requests

NEUTRAL_PAYLOAD = {
    "ARM": 0,
    "SURGE": 0,
    "SWAY": 0,
    "HEAVE": 0,
    "ROLL": 0,
    "PITCH": 0,
    "YAW": 0,
    "S1": 0,
    "S2": 0,
    "S3": 0,
}


def forward_payload(surge: float, heave: float) -> dict:
    return {
        "ARM": 1,
        "SURGE": surge,
        "SWAY": 0,
        "HEAVE": heave,
        "ROLL": 0,
        "PITCH": 0,
        "YAW": 0,
        "S1": 0,
        "S2": 0,
        "S3": 0,
    }


def post_inputs(base_url: str, payload: dict) -> None:
    """POST a form-encoded payload to /inputs (matches AUVClient's encoding)."""
    url = f"{base_url}/inputs"
    try:
        resp = requests.post(url, data=payload, timeout=2.0)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"POST failed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a timed forward-thrust pulse via /inputs")
    parser.add_argument("--host", default="localhost", help="AUV DB API host (default: localhost)")
    parser.add_argument("--port", default="8000", help="AUV DB API port (default: 8000)")
    parser.add_argument("--surge", type=float, default=0.5, help="Surge value, -1.0 to 1.0 (default: 0.5)")
    parser.add_argument("--heave", type=float, default=-0.15, help="Heave value, -1.0 to 1.0; negative = downward, to counter buoyancy (default: -0.15)")
    parser.add_argument("--duration", type=float, default=10.0, help="Seconds to hold forward thrust (default: 10)")
    parser.add_argument("--rate", type=float, default=10.0, help="POST rate in Hz while moving (default: 10)")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    interval = 1.0 / max(args.rate, 1.0)
    payload = forward_payload(args.surge, args.heave)

    print(f"Sending forward thrust (SURGE={args.surge}, HEAVE={args.heave}, ARM=1) to {base_url}/inputs for {args.duration}s...")

    start = time.monotonic()
    try:
        while time.monotonic() - start < args.duration:
            post_inputs(base_url, payload)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nInterrupted — returning to neutral early.")
    finally:
        print("Returning to neutral (ARM=0, all axes 0)...")
        # Send neutral a few times to make sure it lands even if one POST fails.
        for _ in range(5):
            post_inputs(base_url, NEUTRAL_PAYLOAD)
            time.sleep(0.05)
        print("Done.")


if __name__ == "__main__":
    main()
