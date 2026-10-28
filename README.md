# RobotCore Telemetry

A research platform for collecting and analyzing real-world LoRa communication data using a Raspberry Pi transmitter, GPS, WT901BLE68 IMU, LoRa-E5 radios, and a laptop receiver.

**Live dashboard:** https://robotcore-telemetry.vercel.app  
**Local CSV inspector:** https://robotcore-telemetry.vercel.app/import.html  
**Repository:** https://github.com/lalitkumar790/robotcore-telemetry

## Dashboard capabilities

- Live OpenStreetMap centered on MANIT Bhopal, with GPS points colored by measured RSSI.
- Browser-based LoRa-E5 receiver connection over Web Serial on supported Chrome/Edge browsers; validates RTPv1/RTPv2 CRC and sequence before plotting.
- Device-status panel for browser API support, receiver serial connection, transmitter packets observed, GPS validity, WT901BLE68 IMU, and laptop recording.
- Live charts for RSSI/SNR, roll/pitch/yaw, acceleration and gyroscope, plus an attitude/motion display.
- Interactive 3D coordinate point cloud. RTPv2 has no altitude field, so the point cloud labels its vertical axis as sample progression rather than claiming terrain height.
- Local browser recording to IndexedDB and CSV export for receiver-side data.
- Dual-ended comparison: pair each Pi .rcm mission with its matching laptop receiver CSV. Sequence alignment marks transmitter samples not found in the receiver log at their recorded Pi GPS positions, draws track breaks at missing samples, and summarizes packet delivery by distance bins. A second route pair can be loaded for comparison.

## Capture workflow

1. Open the HTTPS dashboard in current Chrome or Edge.
2. Choose **Device status → Connect receiver**, then select the USB serial port of the LoRa-E5 receiver. The dashboard sends the project's current test-mode/radio configuration at 9600 baud.
3. Select **Start laptop recording**. Only decoded, CRC-valid packets are stored locally in this browser; click **Save laptop CSV** to export the receiver-side log.
4. The Pi's existing transmitter program records .rcm mission samples locally in its missions directory regardless of whether every LoRa packet reaches the receiver.
5. In **Dual-ended capture**, import the matching Pi .rcm and receiver CSV files. For route comparison, import a second matched pair as Route B.

Files selected for inspection are parsed in the browser; the dashboard does not send raw location files to a remote API.

## Important measurement caveats

A sequence absent from the receiver log is classified as **not received**, not automatically as RF propagation loss. The current Pi mission format records a sample before the transmission attempt but does not store a per-sequence transmit result. A missing receiver sequence may therefore reflect RF loss, transmitter send failure, receiver outage, or mismatched/incomplete files. The dashboard also warns about sequence-wrap ambiguity when a receiver log starts mid-mission after a sequence wrap.

The PC receive timestamp is not a sensor-acquisition timestamp. The current RTPv2 payload includes GPS, speed and IMU values but no per-sample timestamp or altitude. The 3D display uses sample progression vertically until an altitude-aware data source is available.

## Repository layout

- `apps/web-dashboard/` — research console, local CSV inspector, live device logic
- `schemas/` — versioned normalized telemetry record schema
- `data/manifests/` — repeatable experiment metadata template
- `data/raw/` — raw-data privacy policy; raw GPS files are excluded from Git
- `docs/` — architecture, data dictionary, repeatable experiments, dual-ended capture
- `research/` — data quality, coverage mapping, link prediction, path planning
- `services/ingestion-api/` — future API requirements
- `hardware/` — destination for Pi transmitter and Windows ground-station source snapshots

## Roadmap

1. Reconcile transmitter and receiver using golden-packet tests and hardware-in-the-loop checks.
2. Record radio configuration, experiment/session IDs, and both endpoint logs.
3. Add a Pi-side transmit-result event log so RF non-reception can be separated from local TX errors.
4. Validate RSSI/SNR, GPS fixes, sequence gaps, duplicates, and source provenance.
5. Build measured coverage maps before evaluating spatial link prediction.
6. Evaluate communication-aware path planning against explicit path and safety baselines.

## Data and privacy

Do not commit raw GPS tracks, private mission files, credentials or .env files. Keep raw files immutable and local/access-controlled; share only reviewed, sanitized examples. GitHub Actions performs syntax/schema checks, not hardware validation.
