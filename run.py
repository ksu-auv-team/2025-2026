import argparse
import subprocess
import sys
import os
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="AUV process manager")
    parser.add_argument('-v', '--verbose', action='store_true', help="Print subprocess output to terminal instead of log files")
    args = parser.parse_args()

    current_dir = os.path.dirname(os.path.abspath(__file__))

    db_manager_dir = os.path.join(current_dir, 'libs/db_manager')
    data_visualizer_dir = os.path.join(current_dir, 'libs/data_visualizer')
    hardware_interface = os.path.join(current_dir, 'libs/hardware_interface/hardware_interface.py')

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    logs_dir = os.path.join(current_dir, 'logs', timestamp)
    os.makedirs(logs_dir, exist_ok=True)

    if args.verbose:
        db_out = dv_out = hw_out = None  # inherit parent stdout/stderr → terminal
        log_files = []
    else:
        db_out  = open(os.path.join(logs_dir, 'db_manager.log'), 'w')
        dv_out  = open(os.path.join(logs_dir, 'data_visualizer.log'), 'w')
        hw_out  = open(os.path.join(logs_dir, 'hardware_interface.log'), 'w')
        log_files = [db_out, dv_out, hw_out]

    db_proc = subprocess.Popen(['bash', 'run.sh'], cwd=db_manager_dir, stdout=db_out, stderr=subprocess.STDOUT)
    dv_proc = subprocess.Popen(['bash', 'run.sh'], cwd=data_visualizer_dir, stdout=dv_out, stderr=subprocess.STDOUT)
    hw_proc = subprocess.Popen([sys.executable, hardware_interface], stdout=hw_out, stderr=subprocess.STDOUT)

    try:
        db_proc.wait()
        dv_proc.wait()
        hw_proc.wait()
    except KeyboardInterrupt:
        print("Terminating processes...")
        db_proc.terminate()
        dv_proc.terminate()
        hw_proc.terminate()
        db_proc.wait()
        dv_proc.wait()
        hw_proc.wait()
        print("Processes terminated.")
    finally:
        for f in log_files:
            f.close()
        if not args.verbose:
            print(f"Logs saved in 'logs/{timestamp}/' directory.")
        sys.exit(0)


if __name__ == "__main__":
    main()
