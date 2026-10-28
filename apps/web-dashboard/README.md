# Web Dashboard (Planned)

The first dashboard milestone is a responsive measured-telemetry viewer, not a model demo.

## Initial screens

1. Experiment list with session date, site label, radio configuration, data quality, and available record count.
2. Track map with valid/invalid GPS locations visibly distinguished.
3. RSSI/SNR and packet-sequence timelines with missing-data indicators.
4. Experiment metadata and downloadable sanitized analysis output.

## Data principles

- Mark measured points separately from interpolated or predicted surfaces.
- Show missing fields rather than silently replacing them with zero.
- Exclude raw private location logs from public builds and source control.
- Make the active dataset and experiment visible so plots are reproducible.

No live backend or predictive model is assumed to exist yet.