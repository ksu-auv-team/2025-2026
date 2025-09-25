import subprocess
import sys
import os


current_dir = os.path.dirname(os.path.abspath(__file__))

db_manager_run = os.path.join(current_dir, 'libs/db_manager/run.sh')
data_visualizer_run = os.path.join(current_dir, 'libs/data_visualizer/run.sh')

logs_dir = os.path.join(current_dir, 'libs/data_visualizer/logs')
os.makedirs(logs_dir, exist_ok=True)

db_log = open(os.path.join(logs_dir, 'db_manager.log'), 'w')
dv_log = open(os.path.join(logs_dir, 'data_visualizer.log'), 'w')

db_proc = subprocess.Popen(['bash', db_manager_run], stdout=db_log, stderr=subprocess.STDOUT)
dv_proc = subprocess.Popen(['bash', data_visualizer_run], stdout=dv_log, stderr=subprocess.STDOUT)

try:
    db_proc.wait()
    dv_proc.wait()
except KeyboardInterrupt:
    print("Terminating processes...")
    db_proc.terminate()
    dv_proc.terminate()
    db_proc.wait()
    dv_proc.wait()
    print("Processes terminated.")
finally:
    db_log.close()
    dv_log.close()
    print("Logs saved in 'libs/data_visualizer/logs' directory.")
    sys.exit(0)
