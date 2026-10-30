# RobotCore Laptop Receiver and Local Field Dashboard

The laptop owns the LoRa-E5 receive serial port, validates RTPv2 CRC/sequence, logs received telemetry, and receives encrypted Pi pairing beacons. In managed-session mode it writes a receiver CSV only while a paired capture is active. It also serves the dashboard locally so the dashboard can discover and control the Pi without a laptop Cloudflare tunnel.

## One-time setup on Windows

From PowerShell in this folder:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    py -m pip install --upgrade pip
    pip install -r requirements.txt

The launcher detects the LoRa-E5 by USB ID 10C4:EA60 and re-discovers it after USB/COM changes.

## One-time shared pairing-key provisioning

Run start_field_station.ps1:

    .\start_field_station.ps1

On first launch only, paste the Base64 256-bit pairing key printed by the Pi install_field_console.sh installer. It is saved in %USERPROFILE%\.robotcore\pairing.key with a restricted file ACL. This key is shared only with the Pi and laptop; do not put it in Git, a URL, the dashboard, or a public issue.

The launcher then starts:
- the LoRa-E5 receiver bridge on TCP 8765, bound to the laptop's LAN interfaces;
- managed-session mode, so CSV writing begins only after a Start request;
- the local dashboard at http://<laptop-ip>:8765/;
- authenticated APIs for bridge status, pairing discovery and paired start/stop.

Keep the PowerShell process running during the walk. It prints the per-run bridge token used for the browser bootstrap; the local dashboard receives it in memory and does not save it to Vercel/local storage. Anyone who can access this dashboard on the private LAN can use its controls, so use a trusted private network only.

The laptop does not start cloudflared. The Pi starts its own Quick Tunnel after it discovers internet and sends the URL + a short-lived bearer token to the laptop in an AES-GCM encrypted RCP1 LoRa beacon.

## Private-network firewall

If the phone cannot reach http://<laptop-ip>:8765/, open PowerShell as Administrator and run:

    .\setup_field_station_firewall.ps1

This is a Private-profile-only inbound rule. Do not allow the bridge on Public Wi-Fi or port-forward 8765 to the internet.

## Legacy/manual mode

For isolated receiver debugging, a legacy command can still be used:

    py bridge.py --port COM8 --experiment-id MANIT-20261030-A

To use automatic COM rediscovery, omit --port and do not set ROBOTCORE_RX_PORT. For the new paired workflow, prefer start_field_station.ps1; it applies --host 0.0.0.0 --allow-lan-origins --managed-sessions and the pairing key.

## Session files

Each paired run produces a laptop CSV named:

    receiver_<experiment-id>_<session-id>.csv

The Field Session ID is a column in the CSV. The Pi mission, .events.jsonl sidecar, and .manifest.json include the same ID. Pair the four files in the dashboard's Dual-ended capture section. Session Replay uses Pi-side acquisition timestamps from the JSONL sidecar when available; without it, playback is sample-index based, since RTPv2 RCM packet records have no per-sample timestamp.

## Receiver and pairing status

- serial_connected means Windows opened the selected serial port.
- radio_configured means the LoRa-E5 configuration command was acknowledged.
- packets_received counts decoded RTP telemetry packets; RCP1 pairing beacons are not counted as telemetry or corrupt packets.
- pairing_received counts decrypted/authenticated pairing beacons.
- pairing_rejected counts beacons that failed decrypt/expiry/descriptor validation.
- last_pairing_error explains missing key, wrong key, expired or malformed beacons.
- capture_active means the session CSV is open and being written.
- last_error reports serial/radio or packet-decoding problems.

A modem TX DONE event is not proof that the laptop received the packet. The merged replay retains sender-side TX outcome and receiver-side receipt separately.
