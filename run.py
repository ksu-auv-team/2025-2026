import subprocess
import sys
import os


def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))

    db_manager_dir = os.path.join(current_dir, 'libs/db_manager')
    data_visualizer_dir = os.path.join(current_dir, 'libs/data_visualizer')
    hardware_interface = os.path.join(current_dir, 'libs/hardware_interface/hardware_interface.py')

    logs_dir = os.path.join(current_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)

    db_log = open(os.path.join(logs_dir, 'db_manager.log'), 'w')
    dv_log = open(os.path.join(logs_dir, 'data_visualizer.log'), 'w')
    hw_log = open(os.path.join(logs_dir, 'hardware_interface.log'), 'w')

    db_proc = subprocess.Popen(['bash', 'run.sh'], cwd=db_manager_dir, stdout=db_log, stderr=subprocess.STDOUT)
    dv_proc = subprocess.Popen(['bash', 'run.sh'], cwd=data_visualizer_dir, stdout=dv_log, stderr=subprocess.STDOUT)
    hw_proc = subprocess.Popen([sys.executable, hardware_interface], stdout=hw_log, stderr=subprocess.STDOUT)

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
        db_log.close()
        dv_log.close()
        hw_log.close()
        print("Logs saved in 'logs/' directory.")
        sys.exit(0)


if __name__ == "__main__":
    main()
