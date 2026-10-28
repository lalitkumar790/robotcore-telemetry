# Web Dashboard

The current static dashboard is served from this folder via Vercel.

## Live functionality

- Leaflet / OpenStreetMap map centered on MANIT Bhopal; the map only centers on a live GPS fix after one arrives.
- Web Serial connection for a user-selected LoRa-E5 receiver on supported secure Chrome/Edge contexts; the browser sends the established AT test-mode/radio configuration and parses LoRa-E5 RX metadata lines.
- RTPv1 (17-byte GPS) and RTPv2 (35-byte GPS/IMU) decoding with CRC-16/CCITT-FALSE validation.
- Live RSSI/SNR, sequence-gap/PDR counters, IMU orientation/acceleration/gyroscope charts, and a rotating browser canvas point cloud.
- Device status for selected serial hardware, RTP frames observed from the transmitter, GPS validity, WT901BLE68 direct BLE, and local recording.
- IndexedDB laptop-side recording and CSV download.
- Paired Pi .rcm + receiver CSV analysis, received/not-received sample map, distance-binned PDR comparison, optional Route B, and CSV export.

## Permissions and runtime requirements

- Use HTTPS and a current Chrome/Edge browser for Web Serial and Web Bluetooth. The user must explicitly select a USB port or Bluetooth device in the browser permission chooser.
- A serial radio port can be owned by only one process at a time. Stop the desktop receiver application before opening that same COM/TTY port in this page.
- The page does not silently enumerate unapproved devices and does not upload selected CSV or mission files.
- OpenStreetMap base tiles require an internet connection. Live telemetry, IndexedDB recording and file analysis run in the browser.

## Truthful measurement semantics

- The live route line breaks on missing/out-of-order packet sequences.
- RTPv2 has no per-sample timestamp or altitude field; PC receive time is not a measurement time, and the 3D cloud's vertical axis is sample progression rather than terrain height.
- The Pi .rcm is the transmitter's sample record; the receiver CSV is the observed subset. A sample absent from the receiver log is classified not received, but may represent RF loss, TX command failure, receiver outage, or mismatched logs. The current mission format does not persist a per-sequence transmit result.

See [dual-ended capture](../../docs/dual-ended-capture.md) for the full workflow and analysis caveats.
