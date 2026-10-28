# Coverage Mapping Workstream

Build measured, auditable spatial summaries before attempting prediction.

## First outputs

- GPS track with invalid fixes visibly flagged.
- RSSI and SNR plotted against position and time.
- Packet delivery/loss summaries per session and spatial segment, with the denominator stated.
- Map overlays that distinguish measurements from interpolated/estimated areas.
- Exportable figures with experiment ID, radio settings, timestamp range, and data-quality summary.

Do not silently interpolate across large gaps. Treat coordinate/time alignment, receiver metadata, antenna orientation, and location privacy as first-class concerns. A map of observed measurements is not a predictive coverage model.