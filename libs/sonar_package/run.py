import argparse
from .sonar_utils import Sonar

def main():
    parser = argparse.ArgumentParser(description="Sonar System")
    parser.add_argument("--ip", type=str, default="localhost", help="Server IP address")
    parser.add_argument("--port", type=int, default=5000, help="Server port number")
    args = parser.parse_args()

    sonar_sensor = Sonar(args.ip, args.port)
    sonar_sensor.run()

if __name__ == "__main__":
    main()
