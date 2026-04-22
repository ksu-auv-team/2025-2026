import smbus2


def scan_i2c_bus(bus_number: int = 2) -> list[str]:
    devices = []
    with smbus2.SMBus(bus_number) as bus:
        for addr in range(0x03, 0x78):
            try:
                bus.read_byte(addr)
                devices.append(f"0x{addr:02X}")
            except OSError:
                pass
    return devices


if __name__ == "__main__":
    found = scan_i2c_bus(7)
    if found:
        print(f"Found {len(found)} device(s) on bus 7:")
        for addr in found:
            print(f"  {addr}")
    else:
        print("No devices found on bus 7.")
