import argparse
from .camera_utils import WebCamService

def main():
    parser = argparse.ArgumentParser(description="Camera System")
    parser.add_argument("--ip", type=str, default="localhost", help="Server IP address")
    parser.add_argument("--port", type=int, default=5001, help="Server port number")
    args = parser.parse_args()

    camera_sensor = Camera(args.ip, args.port)
    camera_sensor.run()

if __name__ == "__main__":
    main()