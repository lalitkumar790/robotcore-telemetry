# RobotCore Telemetry

A research-driven robotics platform for collecting and analyzing real-world LoRa communication data. The project integrates Raspberry Pi, GPS, IMU sensors, and LoRa-E5 radios to build location-aware communication maps, study link quality, and support future communication-aware path planning for mobile robots.

## Research status

This repository is being structured as a reproducible research and engineering workspace. Coverage mapping, prediction, and communication-aware path planning are research milestones, not claims of completed functionality.

## Planned workspace

- `hardware/pi-transmitter/` — Raspberry Pi telemetry transmitter snapshot
- `hardware/windows-groundstation/` — Windows receiver and ground-station snapshot
- `hardware/legacy-loramapper/` — legacy project snapshot retained for comparison
- `data/` — data schemas, manifests, and local-only raw data
- `docs/` — architecture, audit notes, data dictionary, and experiment protocol
- `research/` — data quality, coverage mapping, link prediction, and path planning
- `services/` — future ingestion API
- `apps/` — future web dashboard

## Data and privacy

Do not commit raw GPS tracks, private missions, credentials, `.env` files, or identifiable field logs. Keep raw data local and use manifests and validated, sanitized exports when sharing research results.

## Initial workflow

1. Validate transmitter/receiver protocol compatibility with golden packet tests.
2. Record reproducible experiments with radio settings and session metadata.
3. Validate timestamp, GPS, RSSI/SNR, sequence, and packet-loss quality.
4. Build measured coverage visualization before evaluating predictive models.
5. Evaluate prediction and route planning only after collecting sufficient validated field data.

See `docs/` and `research/` as these are added to the repository.
