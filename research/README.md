# Research Workspace

This directory keeps paper-development material separate from the benchmark
implementation.

| Directory | Purpose | Repository policy |
|---|---|---|
| `planning/` | Roadmaps and active task notes | Private; ignored |
| `rebuttal/` | Reviewer text and response drafts | Private; ignored |
| `executive/` | Internal briefs and decision documents | Private; ignored |
| `literature/` | Local papers, extracted text, and source archives | Local; ignored |
| `presentations/` | Slides, renders, videos, and talk assets | Local; ignored |

Production documentation belongs in `docs/`. Reproducible analysis code belongs
in `scripts/analysis/`; reusable pipeline logic belongs in `src/`.

Raw annotation exports remain in the root-level `annotation/` directory for
compatibility with the existing analysis script. They are local data and are
ignored by Git.
