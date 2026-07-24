# archive/

Material kept for **provenance and reproducibility** but not needed to run,
understand, or evaluate the current system. Nothing here is imported by the
application; nothing here is required reading. The live product is documented in
the top-level [README.md](../README.md), [Guide.md](../Guide.md), and [docs/](../docs/).

| Folder | What | Why it's here, not in the live tree |
|---|---|---|
| `data-exports/` | The ML training dataset (`awards_training.csv`, `companies.csv`) + trainer byproducts (`top3_results.json`, `model_report.json`, `company_matcher.joblib`, the export zip, a dated tenders snapshot). | Regenerable byproducts of `exports_ml_pipeline.py`. The **runtime** model artifact (`exports/model_params.json`) stays in [exports/](../exports/); only the bulky inputs/outputs are archived. The trainer reads/writes here — see [README_ML_PIPELINE.md](../README_ML_PIPELINE.md). |
| `planning/` | Original project plan, extended description, and a dated structure snapshot. | Historical planning docs, superseded by the current [docs/](../docs/) and the graded course reports. |
| `internal-logs/` | Engineering working logs: `Notes.md` (improvement log), `integration_gap_tracker.md` (gap backlog), `matching_pipeline_smoke_record.md` (live-smoke records). | Day-to-day development history — useful context, but not part of the user-facing documentation set. |
| `data-samples/` | Small CSV snapshots of `awards` / `companies` / `tenders` from May 2026. | Point-in-time samples used during early development. |

## Why `data-exports/` is kept (and shipped despite its size)

`exports/model_params.json` — the logistic-regression weights the running matcher
loads — is an opaque blob on its own. `data-exports/` holds the exact inputs that
produced it: `awards_training.csv` (21,015 real EU contract-award notices) and
`companies.csv` (the deduplicated winner catalog). Keeping them makes the model
**reproducible and auditable** — `python run_pipeline.py` retrains the ranker from
this data and regenerates `model_params.json`, reproducing the Hit@1/3/5 figures
reported in [README_ML_PIPELINE.md](../README_ML_PIPELINE.md). Without this folder
the model could neither be retrained nor its evaluation independently verified —
which, for a GenAI course submission graded partly on rigor, is the whole point of
shipping the training data alongside the trained artifact. That reproducibility is
why the ~30 MB earns its place; it is otherwise inert (nothing at app runtime reads
it — the app only loads `exports/model_params.json`).

Third-party course material (lecture PDF, grading criteria), presentations
(`*.pptx`), Word documents (`*.docx` — the graded reports and the v2 proposal,
submitted separately via Moodle; the proposal's Markdown source is under
`planning/`), and the pitch video are intentionally **not** in the repository at
all — they're kept locally and delivered separately (see `.gitignore`).
