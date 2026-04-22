from i2cscanner import scan_i2c_bus


def main():
    print("Scanning I2C bus 7 for devices...")
    devices = scan_i2c_bus(7)
    if devices:
        print(f"Found {len(devices)} device(s) on bus 7:")
        for device in devices:
            print(f"  {device}")
    else:
        print("No devices found on bus 7.")

if __name__ == "__main__":
    main()