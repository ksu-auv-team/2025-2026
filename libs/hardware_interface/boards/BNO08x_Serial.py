import serial
import time

from ..message_handler import MessageHandler, Message
from typing import Optional


class BNO08x_Serial:
    """BNO08x Serial Interface

    This class provides an interface to communicate with the BNO08x sensor over a serial connection.
    """
    def __init__(self, port : str = '/dev/ttyACM0', baud : int = 115200, timeout : float = 0.1):
        """Initialize the BNO08x Serial Interface

        Args:
            port (str): The serial port to connect to. Default is '/dev/ttyACM0'.
            baud (int): The baud rate for the serial connection. Default is 115200.
            timeout (float): The read timeout in seconds. Default is 0.1 seconds.
        """
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.serial = None
        self.message_handler = MessageHandler(src_id=0x00, dst_id=0x50)

    def begin(self):
        """Begin communication with the BNO08x sensor."""
        if self.serial is None:
            self.serial = serial.Serial(self.port, self.baud, timeout=self.timeout)
        self.serial.flush()
        time.sleep(1)

    def end(self):
        """End communication with the BNO08x sensor."""
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def write(self, data: dict):
        """
        Write a message to the BNO08x sensor.

        @param data: The message data to send.
        """
        if self.serial is not None:
            msg = self.message_handler.build_post(data, as_binary=False)
            if isinstance(msg, str):
                msg = msg.encode('utf-8')
            self.serial.write(msg)
        else:
            raise RuntimeError("Serial connection not initialized. Call begin() before write().")

    def read(self) -> Optional[Message]:
        """
        Read a message from the BNO08x sensor.
        """
        if self.serial is not None:
            if self.serial.in_waiting > 0:
                raw_data = self.serial.read(self.serial.in_waiting)
                try:
                    message = self.message_handler.parse(raw_data)
                    return message
                except Exception as e:
                    print(f"Error parsing message: {e}")
                    return None
            else:
                return None
        else:
            raise RuntimeError("Serial connection not initialized. Call begin() before read().")
        
    