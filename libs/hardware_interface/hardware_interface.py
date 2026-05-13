# Local imports
from .process_manager import ProcessManager
from .scanner import scan_i2c_bus


def detect_i2c_devices(bus_number: int) -> list[int]:
    """Detect I2C devices on the specified bus and return their addresses."""
    return scan_i2c_bus(bus_number)


