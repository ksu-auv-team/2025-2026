from . import hardware_interface
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the hardware interface.")
    parser.add_argument("--qualify", action="store_true", help="Run in qualification mode.")
    args = parser.parse_args()

    hardware_interface.run(qualify=args.qualify)