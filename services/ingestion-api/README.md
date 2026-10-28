# Ingestion API (Planned)

The future API will accept validated, normalized records and experiment manifests. It is not implemented yet.

## Initial design requirements

- Validate incoming payloads against a versioned schema.
- Require experiment/session identifiers and preserve timestamp semantics.
- Enforce request-size limits, authentication, rate limits, and bounded retention.
- Never expose precise location telemetry through unauthenticated endpoints.
- Store provenance and schema version with each accepted batch.
- Provide idempotent ingestion or duplicate detection.
- Keep credentials in environment secrets; never commit `.env` files.

Start only after local offline validation and the measured coverage pipeline are reliable.