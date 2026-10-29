# Local field-session console

The local Field Console replaces manual Pi systemctl start/stop commands and the phone-facing Cloudflare Quick Tunnel for new field runs. It gives one generated session_id to the Pi and laptop receiver, preflights the Pi's USB/BLE devices, checks the laptop radio, displays startup/retry logs, and stops both capture files from one screen.

## Network model

- The Pi serves the mobile UI locally at http://<PI-IP>:8766/field-console.
- The laptop receiver bridge listens on TCP 8765 on the private LAN and exposes authenticated status/start/stop endpoints.
- Phone, Pi and laptop must be mutually reachable on the same private router/hotspot. Some campus Wi-Fi networks block client-to-client traffic. If the Pi and laptop are on different subnets, join all three to a private hotspot/router rather than adding a public tunnel.
- This is intentionally a local-LAN setup; do not port-forward ports 8765 or 8766, and do not use the control UI on an untrusted/public network.
- Cloudflare is not involved in capture control. A phone/browser disconnect will not stop the local recorders; reconnect to the Pi console and press Stop & Save.

## One-time Pi install

Back up any current recording first. The installer disables the previous robotcore-transmitter.service, which was configured to launch field capture automatically at boot. This avoids restart loops creating extra mission files. Existing data is not deleted.

On the Pi:

    cd ~/robotcore-telemetry-field
    git pull --ff-only origin main
    cd hardware/pi-transmitter
    bash install_field_console.sh

The installer installs the console dependencies, creates /etc/robotcore-field-console.env with a local control token, and enables robotcore-field-console.service. It prints the Pi's addresses and the console token. Keep the token private; enter it only into the local field console.

Useful checks:

    sudo systemctl status robotcore-field-console.service --no-pager
    sudo journalctl -u robotcore-field-console.service -n 80 --no-pager

The old auto-recorder is disabled so a reboot won't start a new mission by itself. The field agent starts runner.py only after the Start button is clicked.

## One-time laptop setup

In Windows PowerShell:

    cd "$HOME\robotcore-telemetry-field"
    git pull --ff-only origin main
    cd hardware/laptop-receiver
    .\start_field_station.ps1

This one-click launcher detects the LoRa-E5 adapter by USB ID 10C4:EA60, starts the authenticated bridge in managed-session mode, and prints a laptop LAN URL and one per-run token. Keep this window open.

If the phone cannot reach the laptop, first confirm all three devices are on the same private Wi-Fi/hotspot and the laptop URL uses that network's LAN IP. If Windows Firewall blocks the local request, open PowerShell as Administrator and run:

    cd "$HOME\robotcore-telemetry-field\hardware\laptop-receiver"
    .\setup_field_station_firewall.ps1

The rule is restricted to the Windows Private network profile. Do not enable it for Public networks.

## Each field run

1. Open the Pi console URL printed by the installer on your phone.
2. Press Run preflight checks. GPS USB adapter, LoRa-E5 TX adapter, and WT901BLE68 discovery must pass. A fresh decoded IMU sample and valid GPS fix are checked again by runner.py before samples are sent.
3. In Pair the laptop receiver, enter the laptop http://<laptop-LAN-IP>:8765 URL and the current bridge token printed in PowerShell. Press Check receiver; Serial connected and radio configured must be true.
4. Enter the experiment label, e.g. MANIT-20261030-A. The page generates a unique field session_id.
5. Press Start paired recording. The laptop creates a new receiver_<experiment>_<session>.csv; the Pi names the mission mission_<timestamp>_<session>.rcm and uses the same session ID in its sidecar and manifest. The page shows the Pi log, stage (starting / waiting for IMU / waiting for GPS fix / recording / failed), and files as they appear.
6. Stay near the base station until you see packets increment in the receiver status, then walk the route.
7. Press Stop and save after the walk. It sends a graceful interrupt to the Pi runner and closes the receiver CSV. Keep the .rcm, .events.jsonl, .manifest.json, and matching receiver CSV together.

Do not start a second run while a previous receiver capture is active. The UI prevents that and keeps Stop available if the Pi process exits early while the receiver CSV remains open.

## What the statuses mean

- USB adapter detected is not the same as successful radio configuration.
- BLE discovered is not yet a fresh sensor sample. runner.py waits for a fresh WT901BLE68 reading before creating the mission or transmitting.
- Waiting for GPS fix means the Pi is not fabricating coordinates and will skip GPS-invalid samples until a valid fix arrives.
- Receiver retries mean the laptop serial adapter disconnected or couldn't be opened; its status should expose last_error and retry. USB port number changes are handled by USB VID/PID discovery rather than pinning COM8.
- The phone is a monitor/control UI, not the recorder. Captures remain on the Pi and laptop if the phone loses network, but you need to reconnect to stop the session from the UI.
- A modem TX DONE event is not proof of receiver reception. Post-run comparison uses the Pi mission, Pi events, and laptop receiver CSV.

## Manual recovery

If the local UI stops responding, don't delete the current session files. Inspect:

    sudo systemctl status robotcore-field-console.service --no-pager
    sudo journalctl -u robotcore-field-console.service -n 120 --no-pager

The console service's controlled shutdown asks its child transmitter to stop cleanly. If a child process exited unexpectedly, use the UI log/status to confirm the final session state before starting another run.

See docs/field-collection-runbook.md for legacy/manual capture guidance and post-run reconciliation.
