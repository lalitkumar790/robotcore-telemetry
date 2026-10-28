# Web Dashboard

This static dashboard is served from this folder through Vercel. The laptop bridge is a separate local process; the hosted page never directly reads the laptop's COM port.

## Live and field capabilities

- Leaflet / OpenStreetMap base centered on the established MANIT campus reference point; actual GPS fixes move the view to observed locations.
- Direct receiver mode: user-selected LoRa-E5 USB serial port through Web Serial on secure Chrome/Edge. Only one application can own the radio COM/TTY port at a time.
- Remote phone mode: authenticated, read-only WebSocket to the laptop receiver bridge through a temporary HTTPS tunnel. Paste the tunnel origin and per-run token in Device status.
- RTPv1 (17-byte GPS) and RTPv2 (35-byte GPS/IMU) decoding with CRC-16/CCITT-FALSE validation in direct browser mode.
- Link charts for RSSI/SNR, live sequence-gap/PDR counters, orientation/acceleration/gyroscope charts and a rotating browser-canvas 3D point cloud.
- Device status separates browser support, serial port open, radio configuration response, valid RTP telemetry, GPS fixes, direct WT901BLE68 BLE connection, and local/remote capture status.
- Local IndexedDB capture and receiver CSV export.
- Dual-ended merge of Pi .rcm mission, laptop receiver CSV and optional Pi .events.jsonl sidecar. It marks not-received sample locations at Pi-recorded coordinates and classifies Pi TX outcomes where sidecar events provide evidence.
- Optional second route pair, PDR by distance segment, TX failure counts, route comparison and loss-map CSV export.

## Start the phone-to-laptop bridge

Follow [the field collection runbook](../../docs/field-collection-runbook.md). The short form is:

1. Start the receiver bridge from hardware/laptop-receiver with the experiment ID used by the Pi.
2. Keep the bridge bound to localhost and start cloudflared Quick Tunnel to http://127.0.0.1:8765 in another terminal.
3. Open this hosted dashboard on the phone, choose Device status, and enter the temporary HTTPS tunnel origin and token printed by the laptop bridge.
4. Leave the laptop bridge and tunnel processes running during the field walk. The laptop continues writing its receiver CSV even if the phone disconnects.

The origin allow-list is intentionally narrow. Use the production dashboard origin by default. The Quick Tunnel URL changes when restarted; it is intended for temporary field testing rather than permanent hosting.

## Permissions, privacy and measurement semantics

- Web Serial/Bluetooth require browser permissions; devices cannot be silently enumerated.
- Selected mission, CSV and JSONL files are parsed locally in the page. The dashboard does not upload them to a backend.
- Keep raw GPS tracks, mission files and receiver logs private; do not commit them to the repository.
- A missing receiver sequence means end-to-end not-received, not automatically RF propagation loss. A sidecar TX error can identify a local transmit failure. Modem TX DONE is not a receiver acknowledgement.
- RTPv2 has no measurement timestamp, altitude or IMU-present bit. PC receive time is not sensor acquisition time; the point cloud's vertical axis is sample progression rather than terrain height. Embedded IMU values are unverified unless direct BLE connection on the Pi/phone has been established.
- Compare runs only when radio parameters and test conditions are comparable.

See [dual-ended capture](../../docs/dual-ended-capture.md) and [the field collection runbook](../../docs/field-collection-runbook.md) for data formats and operating steps.
