import argparse
import time

from smbus2 import SMBus


def scan_i2c_bus(bus_number: int) -> list[int]:
    detected = []
    with SMBus(bus_number) as bus:
        for address in range(0x03, 0x78):
            try:
                bus.write_byte(address, 0x00)  # write probe — never triggers onRequest
                detected.append(address)
            except OSError:
                pass
    return detected


def main():
    parser = argparse.ArgumentParser(
        description="Scan an I2C bus for connected devices."
    )
    parser.add_argument(
        "bus",
        type=int,
        help="I2C bus number to scan (e.g. 1 for /dev/i2c-1)",
    )
    args = parser.parse_args()

    print(f"Scanning I2C bus {args.bus}...")
    addresses = scan_i2c_bus(args.bus)

    if addresses:
        print(f"Found {len(addresses)} device(s):")
        for addr in addresses:
            print(f"  0x{addr:02X}")
    else:
        print("No devices found.")

    return addresses


if __name__ == "__main__":
    while True:
        try:
            main()
            time.sleep(5)  # Scan every 5 seconds
        except KeyboardInterrupt:
            print("\nScan interrupted by user.")
            break