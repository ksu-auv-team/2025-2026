import serial.tools.list_ports as list_ports
from sys import platform
import numpy as np
import logging
import serial
import time


class BNO08x_Serial:
    def __init__(self):
        self.logger = logging.getLogger("BNO08x_Serial")
        logging.basicConfig(level=logging.INFO)

        self.logger.info("Checking platform...")
        os_flag = 0
        if platform == "linux" or platform == "linux2":
            os_flag = 1
        elif platform == "darwin":
            os_flag = 2
        elif platform == "win32":
            os_flag = 3
        else:
            os_flag = 0

        self.logger.info(f"Platform check complete. OS: {platform} | OS flag: {os_flag}")

    def _checkIfAvailable(self):
        """
        Check for COM ports availability
        """
        self.logger.info("Checking COM ports availability...")
        available_ports = []
        available_ports = list_ports.comports()
        if available_ports:
            self.logger.info(f"Available COM ports: {available_ports}")
        else:
            self.logger.warning("No COM ports found.")

        # Check for BNO08x identifier by connecting to each available port and listening
        for port in available_ports:
            try:
                self.device = serial.Serial(port.device, 115200, timeout=1)
                with self.device as ser:
                    response = ser.read(100)
                    if b'BNO08x' in response:
                        time.sleep(0.5)
                        self.device.write(b'1')
                        self.logger.info(f"Found BNO08x on {port.device}")
                        return port.device  # Return immediately when found
            except Exception as e:
                self.logger.error(f"Error connecting to {port.device}: {e}")
        return None  # Return None if not found
    
    def connect(self, port : str = None):
        """
        Connect to the BNO08x sensor via serial port
        """
        self.logger.info("Attempting to connect to BNO08x sensor...")
        if port is None:
            port = self._checkIfAvailable()
            if port is None:
                self.logger.error("BNO08x sensor not found on any COM port.")
                return None

        try:
            self.serial_connection = serial.Serial(port, 115200, timeout=1)
            self.logger.info(f"Connected to BNO08x sensor on {port}")
            return self.serial_connection
        except Exception as e:
            self.logger.error(f"Failed to connect to {port}: {e}")
            return None

    def disconnect(self):
        """
        Disconnect from the BNO08x sensor
        """
        self.logger.info("Attempting to disconnect from BNO08x sensor...")
        if self.serial_connection is not None:
            self.serial_connection.close()
            self.logger.info("Disconnected from BNO08x sensor.")
        else:
            self.logger.warning("No active connection to disconnect.")

    def read_data(self):
        """
        Read data from the BNO08x sensor
        """
        self.logger.info("Attempting to read data from BNO08x sensor...")
        if self.serial_connection is not None:
            try:
                raw = self.serial_connection.read(6)
                if len(raw) == 6:
                    data = tuple(raw[i] for i in range(6))
                else:
                    data = None
                self.logger.info(f"Read data from BNO08x sensor: {data}")
                return data
            except Exception as e:
                self.logger.error(f"Failed to read data from BNO08x sensor: {e}")
                return None
        else:
            self.logger.warning("No active connection to read data from.")
            return None
        
    def test_operation(self):
        """
        Run Operations Test 
        Should be the same procedure as used in the Hardware Interface
        """
        while True:
            try:
                self.logger.info("Running operations test...")
                self.logger.info("Checking for BNO08x sensor...")
                self.connect()
                if self.device is None:
                    self.logger.warning("No active connection to test.")
                    return None
                else:
                    try:
                        self.logger.info(f"Reading data from BNO08x sensor...")
                        data = self.read_data()
                        self.logger.info(f"Read data from BNO08x sensor: {data}")
                    except Exception as e:
                        self.logger.error(f"Failed to read data from BNO08x sensor: {e}")
            except KeyboardInterrupt:
                self.logger.info("Operations test interrupted by user.")
                self.disconnect()
                break
            time.sleep(1)

if __name__ == "__main__":
    bno08x = BNO08x_Serial()
    bno08x.connect()
    bno08x.test_operation()
    bno08x.disconnect()
