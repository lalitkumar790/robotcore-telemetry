# Dual-ended data capture and connectivity analysis

## Why there are two recording sources

RobotCore's transmitter records a complete .rcm mission on the Raspberry Pi before attempting LoRa transmission. The laptop's receiver log contains only packets it actually decoded, plus receiver-side RSSI/SNR and a PC receive timestamp. These files answer different questions and should not overwrite each other.

- **Pi .rcm mission:** expected transmitter-side sequence and GPS/IMU state for each sample.
- **Laptop receiver CSV:** packets observed by the receiver, sequence numbers, RSSI/SNR, and receive time.
- **Browser capture (optional):** a local, IndexedDB-backed recording of received RTP frames, exportable as a receiver CSV. No raw data is uploaded by the dashboard.

## Live dashboard workflow

1. Open the dashboard over HTTPS in current Chrome or Edge.
2. Select **Device status → Connect receiver** and choose the USB serial port belonging to the LoRa-E5 receiver. The browser cannot silently enumerate unapproved USB devices.
3. The dashboard configures the LoRa-E5 with the project radio profile (865 MHz, SF7, 125 kHz bandwidth, preamble settings and 14 dBm), then reads +TEST metadata and RTP payload lines at 9600 baud.
4. Start **Laptop recording**. Only successfully decoded, CRC-valid packets are counted as received and saved locally. Packet sequence gaps stop the drawn live track; no line is drawn across an inferred gap.
5. Stop recording and select **Save laptop CSV**. The CSV has the received sequence, position, RSSI/SNR, receiver timestamp, and the count of sequence positions inferred missing before each received sample.
6. Get the matching Pi file from its missions/mission_*.rcm directory. Import that mission together with the matching receiver CSV in the dual-ended comparison panel.
7. To compare two routes, load both complete matched mission/receiver pairs. Compare observed delivery ratios by distance-from-start segments and export the per-sample loss map CSV.

## How packet positions are reconstructed

RTPv2's 35-byte payload contains sequence, latitude, longitude, speed, acceleration, gyroscope and Euler angles, protected by CRC-16/CCITT-FALSE. A Pi .rcm file has a 13-byte header followed by those fixed-size records. The receiver CSV is aligned to transmitter records by sequence in record order, including the firmware's 1..65535 wraparound. A transmitter sample whose sequence is absent from the receiver record is marked **not received** at its recorded Pi GPS coordinate.

Live link points are colored by measured RSSI; route comparison points distinguish received vs not received. The browser's local 3D point cloud uses east/north distance and sample progression. **RTPv2 does not record altitude**, so the vertical axis is not a terrain-height claim.

## Important measurement caveats

- A missing receiver record is not automatically proof of RF propagation loss. The current .rcm format records the sample before the transmit call but does not record the per-sequence transmitter's transmit result. A missing receiver sequence can therefore indicate RF loss, transmitter send failure, receiver outage, or an incomplete/mismatched log. It is an end-to-end **not-received** classification until transmit-result events are separately logged.
- Sequence alignment works best when the full receiver log belongs to the same mission and session. If a mission wraps its 16-bit sequence and the receiver CSV begins mid-mission after a wrap, sequence-only matching can be ambiguous because the current on-wire format has no session UUID or transmit timestamp. The dashboard flags mission wraps.
- The PC receive timestamp is not the sensor measurement time. The current RTPv2 packet does not contain a per-sample acquisition timestamp.
- RTPv2 always carries numeric IMU fields but has no IMU-present or sensor-health flag. Those fields alone cannot prove the WT901BLE68 is connected; the dashboard labels them unverified and reports the physical sensor connected only after a direct BLE connection.
- Compare routes under equivalent radio settings, antenna orientation, transmitter/receiver placement and similar conditions. Higher PDR in one field run is evidence for that run, not a universal coverage guarantee.
- Keep the raw .rcm and receiver log immutable, and keep precise GPS tracks local or access-controlled. The dashboard processes selected files in the browser and does not send them to an API.

## Planned improvement to transmitter logging

To distinguish RF loss from failed transmission attempts, add a companion append-only Pi event log with one row per sequence: sequence, local transmit-attempt timestamp, transmit-call attempted, LoRa-E5 command response/result, exception/error code, and local mission filename. Do not alter the fixed-size RCM records unless introducing a versioned mission format. A future receiver bridge can merge this sidecar with the receiver CSV for more specific failure attribution.
