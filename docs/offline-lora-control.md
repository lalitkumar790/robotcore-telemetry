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

The Pi pairing announcer now listens in bounded half-duplex windows while idle.
It accepts authenticated START, STOP, and STATUS commands addressed to its
device ID. START is acknowledged while the announcer still owns the radio,
then dispatched on a separate thread so the field controller can safely pause
the announcer and hand the serial device to the mission runner.

During a mission, the Pi runner polls bounded receive windows after local
sampling/transmission and handles authenticated STOP and STATUS commands.
STOP is acknowledged before the runner exits; the field-agent supervisor then
detects process exit and resumes the pairing announcer. Local mission samples
are written before telemetry TX and remain the source of truth.

The laptop receiver worker remains the sole owner of its serial port. API
requests enqueue downlink packets; the worker stops RX, transmits, and restores
RX. Authenticated ACK/NACK packets are correlated by request ID. The bridge
persists its outbound counter, retries the exact same encrypted packet up to
five times, and only reports command success after a matching authenticated
ACK. The Pi persists its receive high-water mark and cached encrypted reply
under the mission directory so a duplicate retry does not execute a command
twice. Pi health beacons support offline discovery even when no tunnel exists.

The local dashboard offers Automatic, Offline LoRa-only, and Online tunnel
session modes. Offline START and STOP use the laptop bridge's authenticated
control endpoints. Pi mission artifacts remain on the Pi during a fully
offline run; the receiver CSV remains on the laptop and can be synchronized
when connectivity is restored.

## Remaining acceptance work

GitHub Actions verifies source compilation, protocol tests, receiver tests,
and dashboard JavaScript syntax. These are software checks only. Before using
this for a real field experiment, test both physical LoRa-E5 devices with the
actual radio configuration and verify:
- Pi receives START without internet, starts exactly one mission, and produces
  the RCM, events, and manifest files.
- Laptop begins its CSV only after a matching authenticated START ACK.
- STOP is delivered during recording, the Pi flushes and closes its files, and
  the announcer resumes.
- Lost ACKs cause an identical-packet retry and do not duplicate a session.
- Radio loss or laptop failure never stops local Pi sampling.
- A long session can still be stopped after the original beacon has gone stale.

Do not treat modem TX DONE as proof of remote receipt. A command is successful
only after its authenticated ACK is received. Do not deploy to the field Pi or
merge to main until the hardware acceptance checks pass.
