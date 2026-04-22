import subprocess
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config() -> dict:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def main() -> None:
    config = load_config()
    hardware = config.get("hardware", {})

    processes: list[subprocess.Popen] = []

    if hardware.get("motors", False):
        motors_module = str(PROJECT_ROOT / "libs" / "hardware_interface" / "modules" / "motors.py")
        proc = subprocess.Popen([sys.executable, motors_module])
        processes.append(proc)
        print("Motors: started")

    if not processes:
        print("No hardware modules enabled in config.yaml")
        return

    try:
        for proc in processes:
            proc.wait()
    except KeyboardInterrupt:
        print("Shutting down hardware interface...")
        for proc in processes:
            proc.terminate()
        for proc in processes:
            proc.wait()
        print("Hardware interface stopped.")


if __name__ == "__main__":
    main()
