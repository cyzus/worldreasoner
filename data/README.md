# Local Dataset Workspace

## Layout

| Path | Contents |
|---|---|
| `versions/v1/` | Immutable snapshot of the submitted benchmark |
| `versions/v2_0/` | Working v2.0 database and reproducibility manifest |
| `selections/` | Ad hoc question or news ID selections |

SQLite files are local and ignored by Git. Release manifests are tracked and
record database checksums, question-ID checksums, counts, provenance, and applied
operations.

Do not move or overwrite root-level legacy databases yet. Existing scripts still
refer to names such as `combined_new.db`; versioned releases are created from
those sources through `wr dataset create-v2`.
