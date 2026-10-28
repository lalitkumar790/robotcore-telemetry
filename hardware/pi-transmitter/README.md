# RobotCore Pi Transmitter

This is the Raspberry Pi field-capture entry point. It keeps the on-air RTPv2/RCM layout compatible with the existing transmitter snapshot while making device detection, sensor-health reporting and transmit outcomes explicit.

## Hardware roles

- GPS receiver: USB serial NMEA RMC sentences at 9600 baud. The known adapter ID is 1A86:7523 but discovery also accepts an explicit port override.
- Seeed LoRa-E5 transmitter: USB serial AT interface at 9600 baud. Known adapter ID 10C4:EA60; explicit override supported.
- WitMotion WT901BLE68: BLE notifications on FFE4 (service FFE5); the address can be pinned with an environment variable. Discovery retries and reports health instead of treating default zero values as a connected sensor.
- Mission storage: .rcm is unchanged: a 13-byte RCM1 header followed by 35-byte RTPv2 records. A sibling .events.jsonl sidecar records GPS/IMU availability and LoRa transmit outcomes. A .manifest.json describes the run.

## Setup on Raspberry Pi OS

From this folder:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    python device_check.py
    python runner.py

The transmitter performs an IMU startup preflight before creating mission files or sending packets. By default it waits up to 90 seconds for a fresh decoded WT901BLE68 reading; if none arrives, it exits instead of starting a mission with zero-valued IMU fields. Adjust this limit with `--imu-startup-timeout 120`. After startup, the sidecar continues to mark any later IMU disconnect or stale reading explicitly. The first GPS fix can take time outdoors. The terminal states that it is waiting; it does not silently transmit a fake location. Once running, a GPS timeout is written to the event sidecar and the loop continues. Local mission logging happens before every radio transmission attempt.

## Device overrides

Use stable /dev/serial/by-id paths where available. If auto-detection sees zero or multiple candidates, it prints the candidate list and stops rather than silently opening the wrong serial port.

    export ROBOTCORE_GPS_PORT=/dev/serial/by-id/YOUR_GPS
    export ROBOTCORE_LORA_PORT=/dev/serial/by-id/YOUR_LORA_E5
    export ROBOTCORE_IMU_ADDRESS=D7:D5:A2:97:34:24
    export ROBOTCORE_EXPERIMENT_ID=MANIT-20261029-A
    python runner.py

Use the same ROBOTCORE_EXPERIMENT_ID on the laptop receiver. Do not run two processes against the same serial device. If a fixed path changes after reconnection, re-run python device_check.py and update the override.

## Files produced

For each run, the program creates three files under missions/ (override with ROBOTCORE_MISSIONS_DIR):

- mission_YYYYMMDD_HHMMSS.rcm — source mission samples, binary-compatible with the existing merger.
- mission_YYYYMMDD_HHMMSS.events.jsonl — one JSON event per line with GPS/IMU health, sample sequence, attempted TX and response classification.
- mission_YYYYMMDD_HHMMSS.manifest.json — experiment ID, radio settings, counts and file names.

Keep all three files together and do not edit the raw files. Copy them from the Pi after the walk and pair the .rcm with the laptop receiver CSV in the web dashboard.

## Important compatibility limits

RTPv2 has no acquisition timestamp, altitude or explicit IMU-presence flag. The event sidecar carries those health facts locally without changing radio bytes. For a sample without a fresh IMU reading, zeroes remain in the legacy-compatible RTPv2 fields but the sidecar explicitly records imu_connected=false; the receiver must not claim those fields prove a physical IMU is connected.
