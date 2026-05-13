from smbus2 import SMBus, i2c_msg


def write(bus_number: int, address: int, data: bytes) -> None:
    """Write bytes to an I2C device."""
    with SMBus(bus_number) as bus:
        msg = i2c_msg.write(address, list(data))
        bus.i2c_rdwr(msg)


def read(bus_number: int, address: int, length: int) -> bytes:
    """Read bytes from an I2C device."""
    with SMBus(bus_number) as bus:
        msg = i2c_msg.read(address, length)
        bus.i2c_rdwr(msg)
        return bytes(msg)


def read_register(bus_number: int, address: int, register: int, length: int) -> bytes:
    """Write a register address then read the response (standard register-based protocol)."""
    with SMBus(bus_number) as bus:
        write_msg = i2c_msg.write(address, [register])
        read_msg = i2c_msg.read(address, length)
        bus.i2c_rdwr(write_msg, read_msg)
        return bytes(read_msg)