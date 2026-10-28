# Field Experiment Protocol

## Before each run

- Assign a unique `experiment_id` and `session_id`.
- Record date/time and timezone, route/site description, operator, robot setup, antenna orientation, approximate mounting height, battery state, and environmental notes.
- Record radio configuration: frequency, spreading factor, bandwidth, transmit power, preamble, coding rate, CRC configuration, antenna, and radio firmware/config version where known.
- Record transmitter and receiver software revisions and identify which hardware components are active.
- Confirm GPS fix and time source. Mark warm-up/fix-acquisition periods instead of silently mixing them with valid data.
- Check that only one process owns each serial receiver port.

## During the run

- Keep raw source logs unchanged.
- Use a consistent telemetry interval and avoid changing several radio settings at once.
- Note stops, occlusions, orientation changes, route changes, interference, resets, and operator interventions.
- Ensure local mission recording continues even if the RF link is temporarily lost, where supported by the installed software.

## After the run

- Copy data to a read-only raw-data location and compute a checksum.
- Validate coordinate ranges, missing values, timestamps, duplicate records, sequence wraparound, session resets, CRC/decode failures, RSSI/SNR units, and GPS quality.
- Distinguish missing packets from malformed packets and receiver/serial outages.
- Produce a derived, versioned dataset without overwriting source data.
- Record exclusions and reasons in a machine-readable manifest.
- Do not publish exact GPS tracks unless sharing them is appropriate and authorized; use sanitized or spatially coarsened data for public examples.

## Analysis rules

- Do not interpret PC arrival time as acquisition time without evidence.
- Evaluate packet delivery and signal quality against a declared denominator and time window.
- Split predictive evaluation by route, session, or spatial region to reduce leakage from neighboring measurements.
- Compare models to simple baselines and report uncertainty and data coverage.
