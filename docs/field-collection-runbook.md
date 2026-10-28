# MANIT Field Collection Runbook

This procedure keeps transmitter-side mission truth on the Pi and receiver-side observations on the laptop. The phone is only a live monitor; it is not the recorder.

## One-time hardware setup on the Pi

From the Pi transmitter folder:

    cd ~/robotcore-telemetry/hardware/pi-transmitter
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    python device_check.py

Check the scan output before starting a run:

- GPS USB adapter is detected. Previously used GPS adapter ID: 1A86:7523.
- LoRa-E5 transmitter USB adapter is detected. Previously used adapter ID: 10C4:EA60.
- WT901BLE68 appears in BLE scan. Previously observed BLE address: D7:D5:A2:97:34:24.

If the GPS or LoRa port is ambiguous, do not guess. Set ROBOTCORE_GPS_PORT and ROBOTCORE_LORA_PORT to the exact device paths reported by the scan. Use stable /dev/serial/by-id paths if available. If WitMotion cannot be found by its advertised name, set ROBOTCORE_IMU_ADDRESS to the address reported by the scan.

Do not use the same serial port for GPS and LoRa. Only one process can own each serial port at a time.

## One-time laptop setup

Install a current Python version, then in PowerShell:

    cd hardware/laptop-receiver
    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    py -m pip install --upgrade pip
    pip install -r requirements.txt
    py -c "from serial.tools import list_ports; [print(p.device, p.vid, p.pid, p.description) for p in list_ports.comports()]"

Stop the old PySide ground-station receiver if it owns the receiver COM port. This bridge must be the single owner of the LoRa-E5 receiver serial interface during the walk.

## Start a field run

Use a new experiment ID and type it in both locations exactly, for example MANIT-20261029-A. Confirm radio settings (865 MHz, SF7, 125 kHz, TX power 14 dBm and current preamble settings) are identical at both ends.

### Pi transmitter terminal

    cd ~/robotcore-telemetry/hardware/pi-transmitter
    source .venv/bin/activate
    export ROBOTCORE_EXPERIMENT_ID=MANIT-20261029-A
    export ROBOTCORE_IMU_ADDRESS=D7:D5:A2:97:34:24
    python device_check.py
    python runner.py

If the port scan does not auto-select correctly, set ROBOTCORE_GPS_PORT and ROBOTCORE_LORA_PORT to the exact paths from the scan before running runner.py.

Wait for the console to report a valid GPS fix. Outdoors, allow the GPS time to acquire a fix. If it says it is waiting, it will record skip events and will not create fake GPS positions. Confirm IMU state in the TX log. If the IMU is waiting/stale, stop and diagnose BLE power, address and notifications before relying on IMU analysis.

The Pi creates three local files in its missions directory:
- mission timestamp .rcm: unchanged RCM1 header and 35-byte RTPv2 sample records.
- same-stem .events.jsonl: per-sample GPS/IMU state, transmit attempt and LoRa TX outcome.
- same-stem .manifest.json: experiment ID, start/end, radio settings, counts and file names.

Leave this process running while walking. Press Ctrl+C when the field run is over, then wait for the saved-files message.

### Laptop receiver bridge terminal

In PowerShell, from hardware/laptop-receiver:

    $env:ROBOTCORE_EXPERIMENT_ID = "MANIT-20261029-A"
    py bridge.py --port COM8 --experiment-id MANIT-20261029-A

Replace COM8 with the actual receiver port shown by Device Manager or the port-list command. If the USB ID uniquely detects the LoRa-E5 receiver, the port argument can be omitted. Keep this terminal open. It writes a receiver CSV locally and logs packets even when your phone disconnects.

The bridge prints a per-run authentication token. Copy it only into the live dashboard in your phone browser. Do not paste it into chat, source control or a shared document.

### Expose it to your phone temporarily

Install Cloudflare Tunnel (cloudflared) on the laptop. Open a second PowerShell window and run:

    cloudflared tunnel --url http://127.0.0.1:8765

Copy the HTTPS trycloudflare URL printed by cloudflared. On your phone open https://robotcore-telemetry.vercel.app, tap Device status, paste the HTTPS URL and the token, then select Connect laptop receiver.

The tunnel hostname is temporary. Keep the tunnel terminal and bridge terminal running throughout the walk. Stop the tunnel after the experiment. This quick-tunnel approach is for a temporary field test, not a permanent service. Quick Tunnels have changing hostnames and no uptime guarantee. Official notes: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ and https://developers.cloudflare.com/network/websockets/.

## After the walk: merge the two sources

1. Stop the Pi transmitter with Ctrl+C, then verify all three mission files exist on the Pi.
2. Stop the laptop bridge after the last data has been logged, then copy its receiver CSV from hardware/laptop-receiver/logs to a private local folder.
3. Copy the Pi .rcm, .events.jsonl and .manifest.json to that same private folder. Keep the raw files unchanged. Do not commit raw GPS files to Git.
4. In the hosted dashboard's Dual-ended capture section choose Route A mission (.rcm), receiver log (CSV), and optional Pi event sidecar (.events.jsonl). Select Analyze packet loss.
5. To compare another route, load a matching second Pi mission, receiver CSV and optional sidecar under Route B. Compare the per-distance-bin PDR and TX failure counts, then export the loss map CSV.

The RCM gives the transmitter's sample coordinates even when the receiver misses a packet. The receiver CSV identifies the packets actually received and supplies RSSI/SNR. The event sidecar attaches per-sequence transmit outcome and sensor health. This is why all three sources should be kept together.

## Interpret the result carefully

- A sample missing from the receiver is “not received,” not automatically RF propagation loss.
- TX failed means the Pi radio command reported a TX error. TX DONE means the modem reported command completion; it is not a receiver acknowledgement.
- Unknown outcome can represent a serial timeout, unclear modem response, receiver outage or an incomplete/mismatched pair.
- The laptop's receive time is not the exact sensor measurement time; RTPv2 has no per-sample timestamp.
- RTPv2 has no altitude field. The dashboard's 3D cloud uses sample progression for its vertical axis rather than terrain elevation.
- A sequence counter wraps at 65535. Always use matching, complete session logs; a receiver CSV that begins mid-mission after a sequence wrap may be ambiguous.
- Compare routes only under the same radio configuration, antenna orientation/height and similar receiver conditions.

## If something is not detected

- GPS missing: run device_check.py; confirm the USB adapter appears; specify ROBOTCORE_GPS_PORT; move outdoors and wait for a valid RMC fix.
- LoRa missing: confirm its USB serial device and VID/PID; specify ROBOTCORE_LORA_PORT; make sure another process is not using it.
- WT901BLE68 missing: run device_check.py; confirm BLE is enabled and the sensor is awake; set ROBOTCORE_IMU_ADDRESS explicitly; check that the device exposes FFE5/FFE4 and that fresh 55 61 notifications arrive.
- Receiver silent: verify the laptop selected the receiver, not GPS; confirm the modem reports radio configuration; check frequency/SF/BW/preamble/power match the transmitter; inspect last_error in Device status.
- Phone says token rejected/origin rejected: create a new bridge run, use the URL and token from the current terminal, and open the production dashboard URL rather than a preview hostname.
