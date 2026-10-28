import asyncio

from config import IMU_ADDRESS, IMU_NAME_HINT
from device_discovery import print_serial_candidates


async def scan_ble():
    try:
        from bleak import BleakScanner
    except ImportError:
        print("Bleak is not installed. Run pip install -r requirements.txt")
        return
    devices = await BleakScanner.discover(timeout=8.0, return_adv=True)
    wanted = IMU_ADDRESS.replace(":", "").replace("-", "").casefold()
    matches = []
    for _key, (device, advertisement) in devices.items():
        address = (getattr(device, "address", "") or "").replace(":", "").replace("-", "").casefold()
        name = getattr(device, "name", None) or getattr(advertisement, "local_name", None) or "(name unavailable)"
        if (wanted and address == wanted) or IMU_NAME_HINT.casefold() in name.casefold() or "wt901" in name.casefold() or "witmotion" in name.casefold():
            matches.append((name, device.address, getattr(advertisement, "rssi", None)))
    if not matches:
        print(f"No WitMotion device found by address/name. Address override: {IMU_ADDRESS or '(unset)'}.")
    for name, address, rssi in matches:
        print(f"BLE candidate: {name} | {address} | RSSI={rssi}")


def main():
    print("=== USB serial scan ===")
    print_serial_candidates()
    print("\n=== BLE scan ===")
    asyncio.run(scan_ble())
    print("\nSet ROBOTCORE_GPS_PORT / ROBOTCORE_LORA_PORT if USB discovery is ambiguous.")
    print("Set ROBOTCORE_IMU_ADDRESS to the BLE address shown above if name filtering is unreliable.")


if __name__ == "__main__":
    main()
