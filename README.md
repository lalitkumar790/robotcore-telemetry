# RobotCore Telemetry

A robotics research platform for collecting and analyzing real-world LoRa communication data. The intended system combines Raspberry Pi, GPS, WT901BLE68 IMU, and LoRa-E5 radios with a ground station and a reproducible research pipeline.

**Dashboard:** https://robotcore-telemetry.vercel.app  
**Local CSV inspector:** https://robotcore-telemetry.vercel.app/import.html  
**Repository:** https://github.com/lalitkumar790/robotcore-telemetry

## Current status

- **Research console:** a static, responsive dashboard scaffold is deployed. No telemetry backend or dataset is connected yet.
- **Data contract:** normalized telemetry JSON schema and an example experiment manifest are included.
- **Research notes:** architecture, data dictionary, field experiment protocol, data quality, coverage mapping, link prediction, and path-planning workstreams are documented.
- **Hardware integration:** the Raspberry Pi transmitter and Windows ground-station snapshots have been audited locally and packed in the starter archive, but those source snapshots still need to be synchronized into this remote repository.

Coverage prediction and communication-aware path planning are future milestones. They are not represented as completed functionality.

## Repository layout

- `apps/web-dashboard/` — static research console prototype
- `schemas/` — versioned normalized telemetry record schema
- `data/manifests/` — experiment manifest template
- `data/raw/` — local/raw-data policy; raw location traces are excluded from Git
- `docs/` — architecture, data dictionary, and repeatable field protocol
- `research/` — data quality, coverage mapping, link prediction, and path planning
- `services/ingestion-api/` — future API requirements
- `hardware/` — destination for transmitter, ground-station, and legacy source snapshots

## Roadmap

1. Verify transmitter/receiver compatibility with golden-packet tests.
2. Capture field sessions with experiment IDs, radio configuration, and timestamp semantics.
3. Validate GPS, RSSI/SNR, sequence handling, packet-loss calculations, and raw-data provenance.
4. Plot measured tracks and link quality before producing any predictions.
5. Evaluate spatial link models with session/route-aware holdouts and simple baselines.
6. Evaluate communication-aware route planning against shortest-path and safety baselines.

## Data and privacy

Do not commit raw GPS tracks, private mission files, credentials, `.env` files, or identifiable field logs. Raw data should remain immutable and local or access-controlled. Share only reviewed, sanitized samples and document transformations.

## Development checks

GitHub Actions performs basic Python syntax compilation and JSON validation. These checks do not replace hardware-in-the-loop tests or experimental validation.
