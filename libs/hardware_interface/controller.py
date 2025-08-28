"""
1    4a    IMU
2    4b    Hydrophone Controller
3    4c    ESC Controller / Depth Sensor
4    4d    
5    4e    Display Controller
6    4f    Torp
7    50    Arm
8    51    PS
"""
import json

config = json.load(open("config.json"))

from .scanner import get_i2c_devices, serial_ports
from .message_handler import MessageHandler
from boards.BNO08x_Serial import BNO08x_Serial
from boards.BNO08x_I2C import BNO08x_I2C
from boards.Motor_Controller import Motor_Controller


class Controller:
    def __init__(self):
        self.i2c_bus_number = config.get("defaultI2CBus", 1)
        self.serial_port = config.get("defaultSerialPort", "/dev/ttyACM0")
        self.message_handler = MessageHandler()

    def scan_i2c(self):
        devices = get_i2c_devices(self.i2c_bus_number)
        return devices

    def scan_serial(self):
        ports = serial_ports()
        return ports
    
    def scan(self):
        i2c_devices = self.scan_i2c()
        serial_ports = self.scan_serial()
        
        return {
            "i2c_devices": i2c_devices,
            "serial_ports": serial_ports
        }
    
    