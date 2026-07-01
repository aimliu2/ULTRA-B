# Sampling Output Convention

The sampler keeps generated runs in the same folder style as the existing
manual resamples:

```text
analysis/resample-PHASE-YYYYMM/sample_records.parquet
```

`PHASE` is passed with `--phase`, for example `--phase a` writes to
`analysis/resample-a-<current-YYYYMM>/sample_records.parquet`.

Use `--run-label resample-a-202301` to target a specific month-like run label,
or pass `--output-dir analysis/resample-a-202301` when the folder path should be
fully explicit. The file stays Parquet; only the run folder naming is aligned.
