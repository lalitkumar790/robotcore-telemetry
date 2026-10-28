from __future__ import annotations

import struct

CRC_POLY = 0x1021


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ CRC_POLY) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def decode_packet(packet: bytes) -> dict:
    """Decode the existing 17-byte RTPv1 or 35-byte RTPv2 packet, with CRC validation."""
    if len(packet) not in (17, 35):
        raise ValueError(f"unsupported RTP packet length {len(packet)}")
    if packet[0] != 0xAA:
        raise ValueError("invalid RTP sync byte")
    version = packet[1]
    crc_expected = struct.unpack(">H", packet[-2:])[0]
    if crc16_ccitt_false(packet[:-2]) != crc_expected:
        raise ValueError("CRC-16/CCITT-FALSE mismatch")

    if version == 1:
        if len(packet) != 17 or packet[2] != 1:
            raise ValueError("invalid RTPv1 size/type")
        _sync, _version, _type, sequence, lat, lon, speed = struct.unpack(">BBBHiiH", packet[:-2])
        return {
            "protocol": "RTPv1", "sequence": sequence,
            "latitude": lat / 1_000_000, "longitude": lon / 1_000_000,
            "speed": speed / 100, "imuPresent": False,
            "roll": None, "pitch": None, "yaw": None,
            "ax": None, "ay": None, "az": None, "gx": None, "gy": None, "gz": None,
            "imu_health": "not_in_packet",
        }

    if version != 2 or len(packet) != 35 or packet[2] != 6:
        raise ValueError("unsupported RTP version/type/size")
    values = struct.unpack(">BBBHiiH9h", packet[:-2])
    (_sync, _version, _type, sequence, lat, lon, speed,
     ax, ay, az, gx, gy, gz, roll, pitch, yaw) = values
    return {
        "protocol": "RTPv2", "sequence": sequence,
        "latitude": lat / 1_000_000, "longitude": lon / 1_000_000,
        "speed": speed / 100, "imuPresent": True,
        "ax": ax / 1000, "ay": ay / 1000, "az": az / 1000,
        "gx": gx / 10, "gy": gy / 10, "gz": gz / 10,
        "roll": roll / 100, "pitch": pitch / 100, "yaw": yaw / 100,
        "imu_health": "unverified_on_wire",
    }
