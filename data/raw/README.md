# Raw Data Policy

Raw field data and `.rcm` mission files may contain precise location trails or experiment-sensitive details. Keep them outside Git by default.

- Preserve source files immutably in local or access-controlled storage.
- Record checksums, capture conditions, experiment/session IDs, and transformation provenance.
- Commit only reviewed, sanitized examples; never commit credentials or precise field tracks without explicit review.
- Do not use raw-data files in a public dashboard build.
- If a dataset must be shared, remove or coarsen location information as appropriate and document the transformation.
