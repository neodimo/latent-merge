# Phase 0 Smoke Contract

Historical smoke target: 2026-05-24 EOD. That date records the original
file-flow checkpoint; it is no longer an active project gate. Current phase
readiness is governed by `LOCKED.md`, `NEXT_STEPS.md`, `PHASE2_GATE.md`, and
the photographic fixture decision in GitHub issue #3.

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

This synthetic fixture remains the deterministic Phase 0 file-flow sentinel; it
does not need to be replaced by a quality-bearing case. Photographic quality
fixtures live in their own intake and must satisfy `LOCKED.md` and
`PHASE2_GATE.md`. Do not fold them into this smoke fixture or present this
fixture as quality evidence.

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
- Model access path: advanced after Phase 0; see `PHASE1.md`,
  `PHASE2_GATE.md`, and `docs/IC_LIGHT_FLUX_STATUS.md` for current backend
  state.
- Smoke pipeline: real file flow, deterministic stub transform

## Bert Parallel Lane

Historical note: this May handoff lane is complete or superseded. The GitHub
repo exists, scaffold and smoke harness work landed, issue tracking is active,
and Gonzo's current `gh` auth works. Bert is parked on this project until Omid
re-engages him; use `WORKFLOW.md`, `AUTOMATION.md`, and `NEXT_STEPS.md` for
current ownership and worker-pulse rules.
