# import serial


# ser = serial.Serial('/dev/ttyACM0', baudrate=115200, timeout=1)

# while True:
#     data = ser.readline()
#     data = data.decode('utf-8').strip().replace('{', '').replace('}', '')
#     data = data.split(',')
#     if data:
#         print(data)

# Example basic usage ^^^

from dataclasses import dataclass
import serial
import time


class BNO08x_Serial:
    def __init__(self, port='/dev/ttyACM0', baudrate=115200, timeout=1):
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)

    def connect(self):
        if not self.ser.is_open:
            self.ser.open()

    def disconnect(self):
        if self.ser.is_open:
            self.ser.close()

    def read_data(self):
        while True:
            data = self.ser.readline()
            data = data.decode('utf-8').strip().replace('{', '').replace('}', '')
            data = data.split(',')
            if data:
                print(data)

    
if __name__ == "__main__":
    bno = BNO08x_Serial()
    bno.connect()
    while True:
        try:
            bno.read_data()
        except KeyboardInterrupt:
            bno.disconnect()
            break