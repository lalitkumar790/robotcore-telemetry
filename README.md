# RobotCore Telemetry

A field-research workspace for measuring LoRa link quality while carrying the Raspberry Pi transmitter around MANIT Bhopal. The system separates transmitter-side sample truth from laptop receiver observations and lets a phone monitor the laptop over an authenticated read-only connection.

Live dashboard: https://robotcore-telemetry.vercel.app
Local CSV inspector: https://robotcore-telemetry.vercel.app/import.html
Repository: https://github.com/lalitkumar790/robotcore-telemetry

## Two separate capture endpoints

### Raspberry Pi transmitter

Code: hardware/pi-transmitter

- Detects the known GPS and LoRa USB IDs, reports all serial devices, accepts explicit port overrides, and fails safely if more than one candidate matches.
- Scans/reconnects to WT901BLE68 BLE in the background, tracks freshness, and exposes connection errors instead of silently claiming IMU health.
- Waits for a valid GPS RMC fix; missing fixes are logged as skipped samples instead of using fabricated/stale coordinates.
- Preserves the existing 35-byte RTPv2 packet and RCM1 mission file structure for compatibility with the working radio receiver.
- Writes three local artifacts for each experiment: the binary .rcm mission, an append-only .events.jsonl sidecar with GPS/IMU and LoRa transmit outcomes, and a .manifest.json with experiment metadata and radio settings.

### Laptop receiver

Code: hardware/laptop-receiver

- Owns the LoRa-E5 receiver serial port in one process.
- Decodes RTPv1/RTPv2, validates CRC, tracks packet sequences, and writes a receiver CSV with receive timestamps, GPS, RSSI/SNR, sequence gaps, PDR and IMU fields.
- Runs an authenticated, read-only WebSocket bridge on localhost.
- The dashboard can connect to this bridge through a temporary tunnel so you can monitor the laptop receiver from your phone while the laptop remains in your room.
- Continues recording locally if the phone loses mobile coverage.

Do not run the existing desktop ground-station receiver and the laptop bridge on the same COM port at once.

## Phone-to-laptop live view

1. Start the Pi transmitter and make sure it reports a current GPS fix and a fresh WT901BLE68 connection.
2. Start the laptop bridge with the same experiment ID as the Pi. Choose the correct receiver port, for example COM8 only if that is what Device Manager lists.
3. The bridge prints a one-run token. Leave the bridge process running.
4. In a second laptop terminal, start Cloudflare Quick Tunnel to http://127.0.0.1:8765.
5. Open the dashboard on your phone, choose Device status, and paste the temporary HTTPS tunnel URL plus the token.
6. Walk with the Pi. The phone shows the latest data that the receiver in your room actually decoded; the laptop keeps its CSV independently.

Quick Tunnel hostnames are temporary and have no uptime guarantee, so this workflow is for a field test rather than a permanent endpoint. See Cloudflare's notes: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ and https://developers.cloudflare.com/network/websockets/.

## Merge after the walk

Keep the three Pi artifacts and the matching laptop CSV together in private local storage:

- Pi .rcm: transmitter sample sequence, GPS, speed and IMU fields for each valid GPS sample.
- Laptop receiver CSV: packets actually received and radio metadata RSSI/SNR, plus receiver time and sequence stats.
- Pi .events.jsonl: per-sequence transmit attempt/result, GPS skips and physical IMU freshness.
- Pi .manifest.json: experiment ID, radio settings, start/end and counts.

In the dashboard's Dual-ended capture section, load the Pi .rcm, the matching receiver CSV and optional Pi event sidecar as Route A. To compare another path, load a second matched set as Route B. The dashboard aligns by sequence, plots received and missing transmitter samples at the Pi coordinates, summarizes PDR by distance segment, shows transmit-failure counts where sidecar evidence exists, and exports a loss-map CSV.

## Important measurement boundaries

- A sample absent from the receiver is classified as end-to-end “not received,” not automatically radio propagation loss. It may represent RF loss, a local transmit failure, receiver outage or mismatched/incomplete logs.
- A modem TX DONE response is not a receiver acknowledgement.
- The RTPv2 packet does not contain a sample-acquisition timestamp, altitude or IMU-presence flag. The sidecar records Pi sensor health; embedded IMU fields alone cannot prove that WT901BLE68 was connected.
- PDR begins at the first sequence observed at the receiver, and therefore excludes unknown losses before that point.
- Sequence numbers wrap from 65535 to 1. Use complete, matching session logs; sequence-only matching can be ambiguous when a receiver log begins mid-mission after a wrap.
- Compare routes only with comparable frequency, SF/BW, TX power, antenna position/orientation and receiver conditions.
- RTPv2 has no altitude field. The holographic point cloud labels vertical progression as sample progression, not terrain height.

## Repository layout

- apps/web-dashboard: live research console, phone bridge controls, route comparison, browser-local recording and CSV inspector
- hardware/pi-transmitter: Pi sensors, TX, device discovery, RCM writer, event sidecar and protocol tests
- hardware/laptop-receiver: receiver CSV logger, read-only WebSocket bridge and protocol tests
- docs/field-collection-runbook.md: complete runbook for field collection and merge
- docs/dual-ended-capture.md: dual-ended capture format and analysis caveats
- schemas, data/manifests and research: data contract and future analysis stages

## Privacy

Raw GPS tracks, mission files, receiver CSVs, BLE addresses when not needed, bridge tokens and .env files should not be committed. Keep source captures immutable and local/access-controlled, and share only reviewed/sanitized data. GitHub Actions runs syntax, JSON, and protocol unit checks; actual GPS, BLE and radio hardware still needs a physical smoke test.
