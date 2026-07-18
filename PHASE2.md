# Phase 2 Evaluation Gate

Historical evaluation target: 2026-06-07 EOD. That date records the old
pre-reset CUDA/sequence checkpoint; it is no longer an active pass gate. The
current Phase 2 gate is the two-layer photographic evaluation defined in
`PHASE2_GATE.md`, blocked on the issue #3 intake ruling and final DiMo
preference review.

## Goal

Prove that the project can evaluate real harmonization results repeatably before adding more model breadth.

Phase 2 is not a new-backend milestone. It is the evaluation and user-surface
lock for the first practical workflow:

```text
artist provides A-side CG + B-side plate + optional matte -> packaged UI run -> saved outputs + review sheet
```

## Locked User Surface

The locked Phase 2 user surface is the packaged local UI.

The surface target remains:

- GitHub release binaries for Linux and Windows.
- The local browser UI launched by those binaries.
- The same output family already used by the CLI: adjusted foreground, final comp, diagnostics, and job metadata.

The CLI remains the reproducibility and automation harness, but it is not the
Phase 2 user surface. Notebooks and Nuke/service integration are out of scope
for this gate.

Release packaging is now governed by GitHub issue #6 and `AUTOMATION.md`: a
new runnable checkpoint should wait until the first accepted photographic
Layer-2 gate. Earlier packaged PCT-Net/UI binaries are historical operational
evidence only; they do not satisfy the current quality or release gate.

Reasoning:

- The UI packaging path exists, so Omid can test real plates without local
  Python setup once photographic evidence is accepted.
- Phase 2 scoring needs fast visual comparison and artifact review, which matches the UI better than a notebook or service.
- The CLI is still useful for smoke tests, baselines, and scripted case runs, but it is a developer surface.

## Acceptance Checklist

**Formal gate definition: [`PHASE2_GATE.md`](PHASE2_GATE.md)** (two-layer: automated hard-rejection + blind A/B visual scoring, with explicit pass criteria). Committed scoring sheet: [`PHASE2_SCORING.md`](PHASE2_SCORING.md). Known-fail list: [`PHASE2_KNOWN_FAILS.md`](PHASE2_KNOWN_FAILS.md).

Note: the technique sweep in `PHASE2_SCORING.md` uses cheap proxy metrics that *rank* techniques but do **not** validate integration quality. The real gate is `PHASE2_GATE.md`.

- ⚠️ 10 varied cases tested and recorded in the scoring sheet. **Met on technique breadth (12 GPU + CPU rounds + IC Flux across 2 fixtures), recorded in `PHASE2_SCORING.md`. NOT met on input-case variety (2 stills + 1 proxy sequence); blocked on DiMo's representative cases per `NEXT_STEPS.md` — see known-fail #4.**
- ✅ At least 1 short proxy sequence tested for flicker. **`fixtures/synthetic_sequence_001` + `scripts/evaluate_sequence_flicker.py`; metrics in `PHASE2_SCORING.md`.**
- ✅ Runtime, memory, and variance baselines committed. **`core/pipeline.py` writes the `runtime` block into `job.json`; RTX 3080 Ti baselines recorded in `PHASE2_SCORING.md`.**
- ✅ Explicit known-fail list committed. **`PHASE2_KNOWN_FAILS.md`.**
- ✅ Packaged UI behavior treated as the user-facing contract for this gate.
  **Historical binaries exist for the Phase 1/PCT-Net path, but the next release
  checkpoint waits for accepted photographic Layer-2 evidence per issue #6.**

Gate status: **defined + Layer 1 ready, not yet passed.** Surface lock and
operational evidence are wrapped; the gate is now formally defined in
`PHASE2_GATE.md` with automated hard-rejection checks implemented
(`scripts/phase2_rejection_checks.py`) and per-backend contact sheets
(`scripts/phase2_contact_sheet.py`). Remaining to *pass*: a locked 10–20 case
eval set (DiMo intake) and a completed blind A/B scoring session meeting the
criteria. Operational readiness is done; quality is gated, not yet certified,
and the next release is deferred until that accepted photographic evidence
exists.

## Scoring Shape

Each case should record:

- Case ID and input fixture.
- Backend and settings.
- Identity preserved.
- Integration improved.
- Plate untouched.
- Edge behavior acceptable.
- Flicker result for sequence cases.
- Runtime and memory notes.
- Known-fail reason, if any.

## Historical 2026-06-07 CUDA/Sequence Checkpoint

Status: partial evidence only. This does not satisfy the 10-case gate.
This checkpoint preserves the old RTX 3080 Ti run measurements; it is not a
claim that the current cron-worker environment can still see CUDA. For current
hardware visibility, read `HARDWARE.md` before scheduling GPU or IC-Light work.

Added artifacts:

- `fixtures/synthetic_sequence_001/` - deterministic 6-frame SDR proxy sequence.
- `scripts/create_sequence_fixture.py` - regenerates that fixture.
- `scripts/evaluate_sequence_flicker.py` - runs a sequence through the normal Phase 1 pipeline and writes `sequence_metrics.json`.
- `scripts/phase2_sequence_video.py` - renders a Discord-viewable MP4 for temporal/flicker review from `sequence_metrics.json`.
- `core/pipeline.py` now records per-run `runtime` telemetry in `job.json`, including duration, process RSS, CUDA visibility, GPU name, total VRAM, and torch peak allocated/reserved memory.
- `scripts/overnight_sweep.py` now records process memory and `nvidia-smi` snapshots per backend.

Historical local run evidence on `cuda:0`:

- GPU: NVIDIA GeForce RTX 3080 Ti, visible as `cuda:0`, `nvidia-smi` reported 12288 MB total; torch reported 11910 MiB total.
- `runs/phase2_cuda0_pctnet_sweep/golden_synthetic_001/job.json`
  - duration: 2.3539s
  - peak torch allocated VRAM: 87.55 MiB
  - peak torch reserved VRAM: 134.0 MiB
  - process max RSS: 1554.05 MiB
- `runs/phase2_cuda0_pctnet_sweep/compositingpro_sh009_minimal/job.json`
  - duration: 2.7772s
  - peak torch allocated VRAM: 163.21 MiB
  - peak torch reserved VRAM: 242.0 MiB
  - process max RSS: 1968.32 MiB
- `runs/phase2_sequence_synthetic_001_pctnet_cuda0/sequence_metrics.json`
  - frames: 6
  - max final-comp temporal RMSE: 0.035383
  - mean final-comp temporal RMSE: 0.032405
  - max foreground temporal RMSE: 0.027275
  - mean foreground temporal RMSE: 0.026053
  - mean frame runtime: 0.4074s
  - max frame runtime: 2.1241s
  - peak reserved VRAM: 120.0 MiB
- `runs/phase2_sequence_synthetic_001_stub/sequence_metrics.json`
  - CPU-safe reference path ran and wrote the same metric schema.

Local artifact note:

- The `runs/phase2_*` outputs are ignored local run artifacts, not committed images. The committed evidence is this checkpoint plus the reusable fixture/tooling; rerun commands are below.

Rerun commands:

```bash
PYTHONPATH=".deps:." python3 scripts/create_sequence_fixture.py --out-dir fixtures/synthetic_sequence_001 --frames 6 --width 384 --height 216
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=".deps:." python3 scripts/evaluate_sequence_flicker.py --sequence-dir fixtures/synthetic_sequence_001 --output-dir runs/phase2_sequence_synthetic_001_pctnet_cuda0 --config configs/phase1_pctnet.json
PYTHONPATH=".deps:." python3 scripts/phase2_sequence_video.py --sequence-metrics runs/phase2_sequence_synthetic_001_pctnet_cuda0/sequence_metrics.json --out runs/phase2_sequence_synthetic_001_pctnet_cuda0/sequence_review.mp4 --title "Phase 2 sequence review"
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=".deps:." python3 cli/run_phase1.py --config configs/phase1_pctnet.json --plate fixtures/golden_synthetic_001/plate_rgb.png --cg fixtures/golden_synthetic_001/cg_rgba.png --alpha fixtures/golden_synthetic_001/alpha.png --output-dir runs/phase2_cuda0_pctnet_sweep/golden_synthetic_001
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=".deps:." python3 cli/run_phase1.py --config configs/phase1_pctnet.json --plate fixtures/compositingpro_sh009_minimal/plate_rgb.png --cg fixtures/compositingpro_sh009_minimal/cg_rgba.png --alpha fixtures/compositingpro_sh009_minimal/alpha.png --output-dir runs/phase2_cuda0_pctnet_sweep/compositingpro_sh009_minimal
```
