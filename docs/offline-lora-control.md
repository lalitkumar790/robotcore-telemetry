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

The Pi-side `LoRaE5.receive_window(timeout_s)` primitive now opens a bounded
`AT+TEST=RXLRPKT` window, captures packet bytes with RSSI/SNR metadata, and
issues `AT+TEST=STOP` before returning. `LoRaE5.transmit()` also stops an
active RX window before TX and enforces the 250-byte payload ceiling. These
operations follow the LoRa-E5 AT command specification, which defines
RXLRPKT as continuous receive and TEST=STOP as the stop sub-command.

This is a tested radio-driver primitive, not yet an end-to-end control path:
the Pi runner does not yet poll windows for RCC1 commands, the announcer does
not yet accept offline START, and the laptop receiver/dashboard do not yet
schedule downlink commands or await authenticated ACKs. The next integration
must add explicit receive windows on both radios, stop-and-wait acknowledgements,
bounded retries, durable replay counters, and safe timeout policy. Do not treat
modem `TX DONE` as proof of reception.

The Pi's local mission recorder remains the source of truth. Radio or laptop
failure must never stop local sampling. Cloudflare pairing remains an optional
online path and existing RCP1/RCS1 beacons remain backward-compatible.
