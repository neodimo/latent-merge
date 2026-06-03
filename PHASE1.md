# Phase 1 Scaffold

Gate date: 2026-05-31 EOD.

## Goal

Turn the Phase 0 smoke contract into the repo's first reproducible runner:

```text
plate RGB + CG RGBA + alpha -> adjusted foreground + final comp + diagnostics + structured job log
```

The current backend is still `mean_match_stub`. It is intentionally not model progress. Its job is to lock the ingest/output shape before IC-Light, DiffHarmony, PCT-Net/AICT, or another real backend replaces it.

## Command

From the repo root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 scripts/smoke_pipeline.py --create-fixture
python3 cli/run_phase1.py --config configs/phase1_stub.json
```

If `python3 -m venv` is unavailable:

```bash
python3 -m pip install --target .deps -r requirements.txt
PYTHONPATH=.deps python3 scripts/smoke_pipeline.py --create-fixture
PYTHONPATH=".deps:." python3 cli/run_phase1.py --config configs/phase1_stub.json
```

Expected outputs:

- `runs/phase1_scaffold/adjusted_fg.png`
- `runs/phase1_scaffold/final_comp.png`
- `runs/phase1_scaffold/delta.png`
- `runs/phase1_scaffold/alpha_weighted_delta.png`
- `runs/phase1_scaffold/alpha_used.png`
- `runs/phase1_scaffold/job.json`

## Backend Interface

The real model backend should keep the same contract:

- read `plate_rgb`, `cg_rgba`, and `alpha`
- return adjusted foreground RGB/RGBA only
- never repaint the plate
- write diagnostics that expose changes and alpha behavior
- save enough metadata for a non-author to reproduce the result

The first real backend should plug into `core/pipeline.py` behind a named backend rather than changing the CLI or output filenames.

## First Real Fixture

Use the free Compositing Pro Nuke CG compositing tutorial files as the first non-synthetic fixture, subject to its personal-practice-only license.

For Phase 1, collapse the material to the smallest useful contract:

- `plate_rgb`
- `cg_rgba` for the creature/foreground
- `alpha`

Do not wire depth, normals, shadows, light groups, or other passes yet. They can become Phase 2/3 conditioning inputs after the baseline proves that plate + foreground + alpha is useful.

## Active Backend Choice

Start with a PCT-Net/AICT-style color-transform harmonization baseline.

Reasoning:

- It is a narrower foreground adjustment than diffusion, so it should preserve CG identity better.
- It is more likely to run cheaply on Gonzo's RTX 3080 Ti setup.
- It fits the current trusted-composite contract: adjusted foreground over untouched plate.

Keep IC-Light V2 / FLUX as a documented alternate path, not the first implementation target.

## Phase 1 Acceptance Checklist

- Reproducible clean-checkout instructions work from `README.md`.
- `job.json` records config, input hashes, backend name, and output paths.
- Outputs include adjusted foreground, final comp, delta, alpha-weighted delta, and alpha used.
- Plate remains untouched outside explicit future interaction passes.
- A real model access path is selected or marked blocked with owner and ETA.
