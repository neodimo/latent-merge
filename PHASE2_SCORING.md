# Phase 2 Scoring Sheet

Durable, committed record of the Phase 2 harmonization evaluation.

Why this file exists: the full sweep artifacts live under `runs/overnight_harmonic_sweep/`
and `runs/overnight_20260530/`, which are **local/ignored** and do not survive a clean
checkout. This file is the committed source of truth for the Phase 2 evaluation gate.
Rendered contact sheets and raw JSON remain in those local run dirs as supporting evidence.

Last consolidated: 2026-06-07.

## Cases evaluated

Phase 2 swept harmonization **techniques** across the available **input fixtures**:

- `fixtures/golden_synthetic_001` — synthetic CG-over-plate still (file-flow/baseline fixture).
- `fixtures/compositingpro_sh009_minimal` — real Compositing Pro shot (sh009), plate + CG creature + alpha.
- `fixtures/synthetic_sequence_001` — deterministic 6-frame SDR proxy sequence (flicker case).

Input-case variety is the known gap: see "Residual gate dependency" below.

## GPU technique sweep (Gonzo, RTX 3080 Ti `cuda:0`)

Metrics (lower = better): `fg_delta_mean` (identity drift), `mean_err_vs_plate`
(integration closeness), `final_std` (composite uniformity in FG region).
Source: `runs/overnight_harmonic_sweep/scores.json`, `phase2_advanced/scores.json`, `ic_flux/scores.json`.

| # | Technique | fg_delta_mean | mean_err_vs_plate | final_std |
|---|-----------|--------------|-------------------|-----------|
| 1 | style_transfer_light | 0.282 | 0.0476 | 0.106 |
| 2 | palette_extract_transfer | 0.282 | 0.0479 | 0.107 |
| 3 | channel_rebalance | 0.278 | 0.0510 | **0.058** |
| 4 | histogram_transfer | 0.277 | 0.0513 | 0.106 |
| 5 | hsv_transfer | 0.278 | 0.0592 | 0.122 |
| 6 | kornia_color_jitter | 0.253 | 0.0662 | 0.077 |
| 7 | gaussian_color_transfer | 0.147 | 0.1574 | 0.118 |
| 8 | lab_transfer | 0.149 | 0.1577 | 0.118 |
| 9 | mean_match_stub | 0.156 | 0.1488 | 0.132 |
| 10 | ycrcb_transfer | 0.124 | 0.2379 | 0.106 |
| 11 | pctnet_harmonize | 0.555 | 0.278 | 0.073 |
| 12 | ic_flux_relight | 0.449 | 0.714 | 0.127 |

## CPU technique sweep (Bert)

CPU rows use a different metric family (`id_drift_rmse`, `integration_rmse`, weighted
`composite_score = id_drift*0.4 + integration*0.6`, lower = better) and are **not**
merged into the GPU table. Source: `runs/overnight_20260530/HANDOFF.md` (synthetic) and
`runs/real_fixture_20260530/sweep_summary.json` (real fixture).

### Synthetic fixture — top candidates

| Rank | Backend | Composite | id_drift | integration |
|------|---------|-----------|----------|-------------|
| 1 | local_spatial 4×4 | **0.1449** | 0.2654 | 0.0646 |
| 2 | local_spatial 2×2 | 0.1450 | 0.2654 | 0.0648 |
| 3 | ensemble (poly+spatial+affine) | 0.1463 | 0.2954 | 0.0470 |
| 4 | polynomial_color (7-term) | 0.1496 | 0.3091 | **0.0432** |

### Real fixture (compositingpro sh009) — top candidates

| Rank | Backend | Composite | id_drift | integration |
|------|---------|-----------|----------|-------------|
| 1 | rgb_affine | **0.1267** | 0.0958 | 0.1473 |
| 2 | lab_mean_std (Reinhard) | 0.1274 | 0.0906 | 0.1519 |
| 3 | histogram_match | 0.1340 | 0.1006 | 0.1563 |
| 6 | polynomial_color | 0.1404 | 0.1896 | **0.1075** |

## Sequence flicker (Gonzo, `cuda:0`)

Source: `runs/phase2_sequence_synthetic_001_pctnet_cuda0/sequence_metrics.json`.
Tooling: `scripts/create_sequence_fixture.py`, `scripts/evaluate_sequence_flicker.py`.

- Fixture: `fixtures/synthetic_sequence_001`, 6 frames, PCT-Net via `configs/phase1_pctnet.json`.
- Max final-comp temporal RMSE: 0.035383; mean: 0.032405.
- Max foreground temporal RMSE: 0.027275; mean: 0.026053.
- Mean frame runtime 0.4074s; peak reserved VRAM 120 MiB.
- A CPU-safe stub reference path (`runs/phase2_sequence_synthetic_001_stub/`) produced the same metric schema.
- Caveat: not optical-flow-aligned; this is a raw frame-to-frame stability read, not a temporal-coherence guarantee.

## Runtime / memory baselines (Gonzo, `cuda:0`)

Recorded into `job.json` `runtime` block by `core/pipeline.py`. GPU: RTX 3080 Ti,
`nvidia-smi` 12288 MB total, torch 11910 MiB total.

| Case | Duration | Peak alloc VRAM | Peak reserved VRAM | Process max RSS |
|------|----------|-----------------|--------------------|-----------------|
| golden_synthetic_001 (PCT-Net) | 2.354s | 87.55 MiB | 134.0 MiB | 1554.05 MiB |
| compositingpro_sh009 (PCT-Net) | 2.777s | 163.21 MiB | 242.0 MiB | 1968.32 MiB |

## Key observations

- Best plate-integration (low `mean_err_vs_plate`): `style_transfer_light` / `palette_extract_transfer` (~0.047).
- Most uniform composite (low `final_std`): `channel_rebalance` (0.058).
- `pctnet_harmonize` makes the most aggressive changes (highest fg_delta 0.555) — strongest relight but most identity movement.
- Synthetic CPU winner (`local_spatial 4×4`) does **not** transfer to real footage; real-fixture CPU winner is `rgb_affine`.
- Open product decision: the CPU composite weights integration 60% / identity 40%, which may be backwards for hero CG assets.

## Residual gate dependency

The acceptance bar "10 varied cases tested and recorded" is met on **technique** breadth
(12 GPU + 9/10 CPU + real-fixture CPU + IC Flux) but **not** on **input-case** variety:
only 2 still fixtures + 1 proxy sequence exist. Closing this needs DiMo's representative
CG-over-plate cases (the 20–30 cases called for in `NEXT_STEPS.md`). That intake is a
project-level dependency, not a code task on this branch.
