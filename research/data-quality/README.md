# Data Quality Workstream

Objective: turn raw field logs into auditable analysis datasets without hiding telemetry failures.

## Checklist

- Validate schema, units, coordinate ranges, timestamp order, and required fields.
- Flag missing GPS fixes, duplicate rows, impossible jumps, malformed packets, and stale sensor readings.
- Analyze sequence gaps with wraparound and session-reset handling.
- Declare the packet-delivery denominator and the difference between RF loss and receiver/software outages.
- Keep raw files immutable; store transformations, exclusions, checksums, and provenance.
- Report row counts and valid/invalid counts by experiment and session.

Do not train prediction models until these checks are implemented and their assumptions documented.