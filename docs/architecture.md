# RobotCore Telemetry — Architecture

## Objective
Build a reproducible field-research pipeline for location-referenced LoRa telemetry. The near-term goal is trustworthy measured coverage visualization; spatial prediction and communication-aware navigation are later milestones, not assumed features.

## System layers

1. **Robot transmitter (Raspberry Pi):** GPS position, WT901BLE68 IMU readings, robot state, packet sequence and CRC, LoRa-E5 transmit path, and local mission recording.
2. **LoRa link:** radio packet delivery and receiver-reported signal metadata, including RSSI and SNR where exposed by the receiver/radio configuration.
3. **Windows ground station:** serial receiver, packet decoding, sequence tracking, live visualization, and replay of recorded missions.
4. **Research data pipeline:** immutable source records, validated telemetry schema, experiment metadata, quality checks, derived datasets, maps, and models.
5. **Future web dashboard/API:** experiment browsing and measured coverage visualization first; prediction and route-planning views only after validation.

## Data principle
Distinguish measurement time, transmit time, and PC receive time. A PC receive timestamp is not automatically the physical measurement timestamp. Track session identifiers, sequence numbers, radio settings, software revision, and data-quality flags.

## Development milestones

- M0: preserve source snapshots and document known risks.
- M1: verify transmitter/receiver compatibility using golden packets and repeatable hardware smoke tests.
- M2: validate and normalize field logs with experiment manifests.
- M3: render measured tracks, RSSI/SNR, packet delivery, and missing/invalid data visibly.
- M4: train spatial link-quality models with session-aware holdout evaluation.
- M5: evaluate communication-aware route planning against explicit baselines and safety constraints.

## Boundaries
Do not claim predictive coverage or robot autonomy based solely on recorded CSV telemetry. Validate every milestone with reproducible tests and field evidence.