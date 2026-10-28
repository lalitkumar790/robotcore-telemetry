# RobotCore Laptop Receiver Bridge

This is the separate laptop-side receiver process for a field walk. It owns the LoRa-E5 receiver serial port, decodes RTPv1/RTPv2 and validates CRC, saves an append-only receiver CSV, and broadcasts only read-only telemetry over an authenticated WebSocket to the hosted dashboard.

## Do not open the same COM port twice

Stop the old PySide ground-station receiver or any other serial process on the LoRa-E5 receiver first. This bridge opens the port exclusively. The laptop continues recording even when your phone disconnects or moves out of mobile coverage.

## Install and start on Windows

From PowerShell in this folder:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    py -m pip install --upgrade pip
    pip install -r requirements.txt
    py bridge.py --port COM8 --experiment-id MANIT-20261029-A

Replace COM8 with the actual RX port found in Device Manager or `py -c "from receiver import list_ports_text; print(list_ports_text())"`. If the known LoRa-E5 USB ID (10C4:EA60) is uniquely detected, --port is optional.

The console prints a per-run bridge token. Keep it private and paste it into the hosted dashboard's Device status panel on your phone.

## Expose the local bridge temporarily to your phone

Install cloudflared on the laptop, leave the bridge process running, and open a second PowerShell window:

    cloudflared tunnel --url http://127.0.0.1:8765

Copy the HTTPS URL ending in trycloudflare.com into the hosted dashboard. The page creates a secure WSS connection to /ws and authenticates with the token. Do not paste the token into the URL. Stop cloudflared when the walk ends; its quick-tunnel hostname is temporary.

The default allowed origin is https://robotcore-telemetry.vercel.app. If you use another Vercel origin, supply it via ROBOTCORE_ALLOWED_ORIGINS or repeated --origin options. The bridge binds to 127.0.0.1 by default; do not bind to 0.0.0.0 for this setup.

## Logs

A new receiver CSV is written under logs/ for each run and flushed after each valid packet. Columns include UTC receive time, sequence, protocol, GPS, RSSI/SNR, cumulative receiver stats, PDR and IMU fields with the status unverified for RTPv2. Raw GPS tracks are private and should not be committed to Git.

## Status semantics

The bridge reports serial connectivity separately from successful radio-configuration acknowledgement and from actual valid RTP packet reception. A serial port open is not proof of LoRa reception. Packet-loss estimates are inferred from sequence gaps after the first packet; they exclude losses before the first observed sequence and may include local receiver/driver issues.

RTPv2 does not carry an IMU presence flag, acquisition timestamp, altitude or transmit outcome. The receiver therefore labels on-air IMU fields unverified. Pair this receiver CSV with the Pi .rcm plus its .events.jsonl sidecar after the walk to classify each transmitter sample as received/not-received and inspect Pi-side TX outcome.
