# Phase 0 Smoke Contract

Gate date: 2026-05-24 EOD.

## Goal

Make the V0 file flow executable before real model work starts:

```text
CG RGBA + plate RGB + alpha/matte -> adjusted foreground + diagnostics -> trusted A-over-B over untouched plate
```

The current Phase 0 harness uses a deterministic stub transform. It does not count as model progress.

## Golden Fixture

Current fixture path:

- `fixtures/golden_synthetic_001/plate_rgb.png`
- `fixtures/golden_synthetic_001/cg_rgba.png`
- `fixtures/golden_synthetic_001/alpha.png`
- `fixtures/golden_synthetic_001/fixture.json`

This synthetic fixture is acceptable for Phase 0 file-flow proof. It should be replaced or augmented by a DiMo-approved production-style fixture as soon as one is available.

## Smoke Command

From `projects/latent-merge`:

```bash
python scripts/smoke_pipeline.py --create-fixture
```

Expected outputs:

- `runs/phase0_smoke/adjusted_fg.png`
- `runs/phase0_smoke/final_comp.png`
- `runs/phase0_smoke/delta.png`
- `runs/phase0_smoke/alpha_weighted_delta.png`
- `runs/phase0_smoke/alpha_used.png`
- `runs/phase0_smoke/job.json`

## Phase 0 Acceptance State

- V0 contract: locked in `SPEC_DRAFT.md`
- Fixture: synthetic golden fixture generated locally
- Input/output filenames: documented here
- Model access path: still needs owner confirmation
- Smoke pipeline: real file flow, deterministic stub transform

## Bert Parallel Lane

Bert can move independently on:

- clone or initialize the actual GitHub `latent-merge` repo
- create scaffold branch with `core/`, `cli/`, `nuke/`, `docs/`, `tests/fixtures/`
- port this Phase 0 smoke harness into the repo as the first reproducible CLI
- verify GitHub auth/permissions because Gonzo's local `gh` token is currently invalid
- open issues for Phase 1: real ingest/output pipeline, model access check, golden fixture replacement, README reproduction path
