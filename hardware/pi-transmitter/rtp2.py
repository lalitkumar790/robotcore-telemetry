from __future__ import annotations

import struct

SYNC = 0xAA
VERSION = 2
PACKET_TYPE_ROBOT_STATE = 6
PACKET_SIZE = 35
HEADER_FORMAT = ">BBBHiiH9h"


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _i16(value: float, scale: int) -> int:
    return max(-32768, min(32767, int(round(value * scale))))


def encode_rtpv2(sequence: int, latitude: float, longitude: float, speed_kmh: float, imu: object | None) -> bytes:
    if not 1 <= int(sequence) <= 65535:
        raise ValueError("sequence must be in range 1..65535")
    if not -90 <= float(latitude) <= 90 or not -180 <= float(longitude) <= 180:
        raise ValueError("GPS coordinates out of range")
    source = imu
    fields = (
        _i16(getattr(source, "ax", 0.0), 1000), _i16(getattr(source, "ay", 0.0), 1000),
        _i16(getattr(source, "az", 0.0), 1000), _i16(getattr(source, "gx", 0.0), 10),
        _i16(getattr(source, "gy", 0.0), 10), _i16(getattr(source, "gz", 0.0), 10),
        _i16(getattr(source, "roll", 0.0), 100), _i16(getattr(source, "pitch", 0.0), 100),
        _i16(getattr(source, "yaw", 0.0), 100),
    )
    payload = struct.pack(
        HEADER_FORMAT, SYNC, VERSION, PACKET_TYPE_ROBOT_STATE, int(sequence),
        int(round(latitude * 1_000_000)), int(round(longitude * 1_000_000)),
        max(0, min(65535, int(round(max(0.0, speed_kmh) * 100)))), *fields,
    )
    return payload + struct.pack(">H", crc16_ccitt_false(payload))


def decode_rtpv2(packet: bytes) -> dict:
    if len(packet) != PACKET_SIZE:
        raise ValueError(f"expected RTPv2 {PACKET_SIZE} bytes; got {len(packet)}")
    if packet[0] != SYNC or packet[1] != VERSION or packet[2] != PACKET_TYPE_ROBOT_STATE:
        raise ValueError("bad sync, version, or packet type")
    if crc16_ccitt_false(packet[:-2]) != struct.unpack(">H", packet[-2:])[0]:
        raise ValueError("CRC-16/CCITT-FALSE mismatch")
    values = struct.unpack(HEADER_FORMAT, packet[:-2])
    (_sync, _version, _type, sequence, lat, lon, speed, ax, ay, az, gx, gy, gz, roll, pitch, yaw) = values
    return {
        "sequence": sequence, "latitude": lat / 1_000_000, "longitude": lon / 1_000_000,
        "speed": speed / 100, "ax": ax / 1000, "ay": ay / 1000, "az": az / 1000,
        "gx": gx / 10, "gy": gy / 10, "gz": gz / 10,
        "roll": roll / 100, "pitch": pitch / 100, "yaw": yaw / 100,
    }
