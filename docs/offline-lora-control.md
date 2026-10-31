# Offline LoRa control protocol (RCC1)

This document specifies the authenticated control-message envelope introduced for
offline field operation. It does not change the existing RTPv2 telemetry or RCP1
Cloudflare pairing formats.

## Envelope

- Magic: `RCC1`
- Payload: compact ASCII JSON, encrypted with AES-256-GCM
- Nonce: 12 random bytes per newly created message
- Authentication associated data: the four-byte magic
- Maximum packet: 250 bytes (LoRa-E5 TEST-mode limit)
- Shared key: the existing 32-byte RobotCore pairing key

Supported message kinds: `START`, `STOP`, `STATUS`, `ACK`, `NACK`.
Each message carries a target device ID, monotonically increasing 64-bit
counter, and request ID. START also carries experiment and session IDs; STOP
carries the session ID. Retries must resend the exact same ciphertext, not
re-encrypt with a new nonce or counter.

## Replay and idempotency

`ControlReplayGuard` rejects counters at or below its high-water mark and
accepts an exact retry with the same request ID and command contents as an
idempotent duplicate. A request ID reused with different content is rejected.
The receiver must persist the high-water counter before acknowledging a new
command. To recover an ACK after reboot, it must also persist the last accepted
request and resulting session state. The in-memory helper alone is not durable.

## Radio scheduling and integration status

RCC1 is the message format and validation primitive; this commit does not yet
wire it to the serial radio workers or dashboard. The current deployment has a
Pi transmitter and laptop receiver operating in different roles. A working
offline control path must implement explicit half-duplex receive/transmit
windows, stop-and-wait acknowledgements, bounded retries, and a safe timeout
policy on both ends. Do not treat modem `TX DONE` as proof of reception.

The Pi's local mission recorder remains the source of truth. Radio or laptop
failure must never stop local sampling. Cloudflare pairing remains an optional
online path and existing RCP1/RCS1 beacons remain backward-compatible.
