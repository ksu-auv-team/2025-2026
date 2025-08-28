import re
import sys
import glob
import serial
import subprocess
from typing import List


def serial_ports() -> List[str]:
    """ Lists serial port names

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result

def get_i2c_devices(bus_number : int = 1) -> List[str]:
    command = ["i2cdetect", "-y", str(bus_number)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
    output, _ = process.communicate()

    devices = []
    for line in output.splitlines():
        # Skip header lines
        if not re.match(r"^[0-9a-f]{2}:", line):
            continue
        
        # Extract addresses from the line
        parts = line.split()
        for i, part in enumerate(parts):
            if i == 0: # Skip the row header (e.g., "00:")
                continue
            if part not in ("--", "UU"):
                # Convert to full hexadecimal address
                row_prefix = line.split(":")[0]
                col_suffix = hex(i - 1)[2:].zfill(1) # Adjust for 0-indexed column
                full_address = f"0x{row_prefix}{col_suffix}"
                devices.append(full_address)
            elif part == "UU":
                row_prefix = line.split(":")[0]
                col_suffix = hex(i - 1)[2:].zfill(1)
                full_address = f"0x{row_prefix}{col_suffix}"
                devices.append(f"{full_address} (in use by kernel)")
    return devices
