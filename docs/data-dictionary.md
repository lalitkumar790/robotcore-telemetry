# Telemetry Data Dictionary

The field names below describe the intended normalized research record. Raw transmitter/receiver field names may differ; normalization must preserve source values and provenance.

| Field | Meaning | Notes |
|---|---|---|
| `experiment_id` | Human-readable experiment identifier | Stable across related runs when appropriate |
| `session_id` | Unique run/session identifier | Distinguishes resets and independent recording sessions |
| `sequence` | Packet sequence number | Handle wraparound and session resets explicitly |
| `measurement_time` | Timestamp of sensor measurement | Keep null if the source does not provide one reliably |
| `transmit_time` | Timestamp when packet is transmitted | Keep distinct from measurement and receive time |
| `receive_time` | Receiver/PC arrival timestamp | Arrival time is not necessarily sensor acquisition time |
| `latitude`, `longitude` | GPS coordinates | Preserve source precision; do not fabricate missing fixes |
| `gps_fix_quality` | GPS validity/quality metadata | Record when available |
| `speed_mps` | Speed in metres per second | Keep unit conversions explicit and testable |
| `heading_deg` | Heading/robot yaw in degrees | Document sensor frame and convention |
| `roll_deg`, `pitch_deg` | Orientation estimates | Document source sensor and reference frame |
| `rssi_dbm` | Received signal strength in dBm | May be missing if radio or receiver does not expose it |
| `snr_db` | Signal-to-noise ratio in dB | Preserve reported units and radio-specific semantics |
| `crc_ok` | Packet integrity check outcome | Unknown is distinct from false |
| `decode_ok` | Payload decoding outcome | Keep invalid packets in quality summaries where possible |
| `radio_config_id` | Reference to radio settings | Must resolve to a manifest/config snapshot |
| `source_file`, `source_row` | Source provenance | Allows derived records to be traced back to raw evidence |

## Rules

- Keep missing values missing; don't coerce them to zero.
- Preserve original data and document transformations.
- Record units and coordinate reference assumptions.
- Store data-quality flags separately from measured values.
- Confirm the exact schema against the installed protocol implementation before using it for analysis.