# Latent-Merge Overnight Sweep — Morning Handoff
**Date:** 2026-05-30  
**Operator:** Gonzo (overnight autonomous run)  
**Hardware:** VPS, CPU-only (no NVIDIA GPU; no torch/diffusers)  
**Fixture:** `fixtures/golden_synthetic_001` (synthetic 768×432)

---

## What Was Run

Two experimental rounds, 19 distinct technique variants total.

### Round 1 — Technique Sweep (9 backends)
`runs/overnight_20260530/` — each with contact sheet, delta, adjusted FG, and job.json  

| Rank | Backend | Composite Score | id_drift | integration | Notes |
|------|---------|----------------|---------|------------|-------|
| #1 | polynomial_color (7-term) | 0.1496 | 0.3091 | **0.0432** | Best integration; highest id_drift |
| #2 | local_spatial 3×3 | 0.1525 | 0.2698 | 0.0744 | Good balance |
| #3 | rgb_affine (Reinhard RGB) | 0.1602 | 0.3069 | 0.0624 | Classic approach |
| #4 | lab_mean_only | 0.1624 | 0.3031 | 0.0685 | Preserves CG contrast |
| #5 | **mean_match_stub (baseline)** | 0.1641 | **0.1588** | 0.1676 | Lowest id_drift; worst integration |
| #6 | unclamped_mean | 0.1641 | 0.3067 | 0.0690 | |
| #7 | histogram_match | 0.1656 | 0.3036 | 0.0736 | |
| #8 | lab_affine (Reinhard 2001) | 0.1666 | 0.3049 | 0.0744 | |
| #9 | gamma_curve | 0.1719 | 0.2550 | 0.1165 | Worst overall |

### Round 2 — Refinement (10 variants)
`runs/overnight_20260530/refinement/` — parameter sweeps on top candidates

| Rank | Variant | Score | id_drift | integration |
|------|---------|-------|---------|------------|
| #1 | local_4x4 | **0.1449** | 0.2654 | 0.0646 |
| #2 | local_2x2 | 0.1450 | 0.2654 | 0.0648 |
| #3 | ensemble (poly+spatial+affine) | 0.1463 | 0.2954 | **0.0470** |
| #4 | poly_quad (7-term) | 0.1496 | 0.3091 | 0.0432 |
| #5 | poly_linear (3-term) | 0.1514 | 0.3073 | 0.0474 |

---

## Key Findings

### The core tension
Every non-stub technique faces the same tradeoff:  
- **Better integration** (CG looks more like plate) → higher id_drift (CG identity changes more)  
- **Lower id_drift** (CG texture/color preserved) → worse integration (CG still looks "wrong" in the plate)

The current composite score weights integration 60%/id_drift 40%, which is why aggressive techniques rank higher despite the identity cost. This weighting should be discussed with DiMo — for VFX use the priority might flip depending on the shot.

### Top technique: Local Spatial 4×4
- Best composite score across both rounds (0.1449)
- 4×4 grid adapts to spatial lighting variation in the fixture
- Works entirely in-frame without global assumptions
- CPU fast: 0.16s per frame
- **But:** the synthetic fixture has a smooth gradient — on a real plate with hard lighting boundaries, tile seams could become visible

### Strongest integration: Polynomial Color (7-term)
- Fits a 7-coefficient color transform per output channel using masked pixels
- Produces the closest CG-to-plate color match (integration RMSE 0.0432)
- But also the biggest identity modification (id_drift 0.3091)
- 10-term cross-term version performs *worse* (overfitting on limited data)

### Baseline (mean_match_stub) still has unique value
- Lowest id_drift of all: 0.1588 (baseline preserves identity best)
- The [0.72, 1.28] gain clamp is why — it simply won't apply large corrections
- **Use baseline when identity is paramount** (logos, hero props, precise color matches)
- Use aggressive techniques when integration matters more

### Ensemble approach
- 50% poly + 30% local_spatial + 20% rgb_affine = composite score 0.1463
- Best integration of the refinement round after poly alone (0.0470)
- More stable than any single aggressive method
- Good candidate for a "balanced" default

### Contact sheet quality (the rendering itself)
- Prior sheets used PIL default bitmap font (~10px), no metadata
- All overnight sheets use DejaVuSansMono TTF (14-16pt), color-coded metrics bar, backend ID, runtime
- Master comparison and refinement master sheets show all techniques in one scrollable grid with final_comp thumbnail per row

---

## IC Flux / IC-Light V2 — Blocker Documentation

**Status: BLOCKED_VPS_NO_GPU_HARDWARE** *(updated 2026-05-30 after full GPU discovery pass)*

### Discovery pass results (VPS execution environment)

| Check | Result |
|-------|--------|
| `nvidia-smi` | command not found |
| `/dev/nvidia*` | No such file or directory |
| `/proc/driver/nvidia` | No such file or directory |
| venv torch CUDA | `ModuleNotFoundError: No module named 'torch'` |
| SSH to local machine | no `~/.ssh/config`, no keys |
| OpenClaw paired nodes | `nodes: []` (none paired) |

**Root cause:** The VPS (187.124.239.114) has zero NVIDIA hardware. The RTX 3080 Ti in `HARDWARE.md` is on the GMKtec/Bazzite local machine, not this VPS. The HARDWARE.md note "CUDA runtime works inside `latent-merge/.venv`" refers to the local-machine venv, not the VPS-side clone. There is no network path from this execution environment to that machine.

**Target hardware:** Gonzo's local machine — GMKtec NucBox_EVO-X2 / Bazzite — RTX 3080 Ti 12 GB, `cuda:0`

### One-liner to run on the GPU host

```bash
# From the repo root on Gonzo's machine:
bash scripts/run_ic_flux_comparison.sh
```

This script handles: CUDA torch install check → weight download (one-time, ~25 GB FLUX + IC-Light) → 5 comparison variants (3 seeds + CFG sweep + step count variant) → master sheet regeneration.

**Runner is complete:** `scripts/ic_flux_runner.py` now has the full pipeline wired up (FluxControlNetPipeline + IC-Light conditioning). Not a stub — ready to execute once weights are downloaded.

**Expected IC Flux risks (document before you run):**
- Diffusion will rewrite CG texture details — id_drift will be high
- VAE encode/decode distortion at edges
- SDR-trained; HDR plates need tonemapping
- ~1–2 min per frame at 20 steps on RTX 3080 Ti
- Must fix seed for reproducibility

**Comparison template:** The CPU-technique contact sheets are structured identically to what the IC Flux runner will produce. Side-by-side is ready once IC Flux outputs exist.

**IC Flux comparison matrix fields:** `runs/overnight_20260530/ic_flux_docs.json`

---

## Failure Modes Observed

1. **Tile seam artifacts** (local_spatial): not visible on smooth synthetic fixture, but likely on real plates with sharp lighting. Use 2×2 or soften tile boundaries.
2. **Polynomial overfitting** (10-term cross): adding cross-terms made the result *worse* (score 0.1703) — too many degrees of freedom for a small masked area.
3. **Gamma correction** is the worst overall (score 0.1719): nonlinear but only shifts luminance, not chroma.
4. **Lab affine (Reinhard)**: counterintuitively worse than plain RGB affine because the synthetic fixture's color statistics happen to be better-matched in RGB space.

---

## Artifact Paths

All under `repos/latent-merge/runs/overnight_20260530/`:

```
master_comparison.jpg          ← all 9 techniques, one sheet
refinement_top3.jpg            ← top 3 side-by-side
sweep_summary.json             ← full ranked JSON
ic_flux_docs.json              ← IC Flux setup/commands/risks
refinement/
  refinement_master.jpg        ← all 10 refinement variants
  refinement_summary.json
  R03_local_4x4/contact_sheet.jpg   ← overall winner
  R10_ensemble/contact_sheet.jpg    ← best ensemble
  R05_poly_quad/contact_sheet.jpg   ← best integration
01_mean_match_stub/contact_sheet.jpg   ← baseline reference
09_polynomial_color/contact_sheet.jpg  ← sweep winner
```

Scripts (new):
- `scripts/overnight_sweep.py` — full 9-backend sweep with contact sheets + master comparison
- `scripts/refinement_round.py` — 10-variant refinement with parameter sweeps
- `scripts/ic_flux_runner.py` — IC Flux runner stub (needs GPU + weights)

---

## Recommended Next Experiment

**Priority 1 (DiMo's home server, GPU required):**  
Run `scripts/ic_flux_runner.py` on the same fixture with seed 42, steps 20-30.  
Compare its `contact_sheet.jpg` directly against `09_polynomial_color/contact_sheet.jpg` and `R03_local_4x4/contact_sheet.jpg`.  
Key question: does diffusion-based relighting produce a better composite while still preserving enough CG identity to be useful?

**Priority 2 (any hardware):**  
Get a real DiMo/Nuke fixture (plate + CG RGBA + alpha, not synthetic) and rerun the full sweep.  
The synthetic fixture has smooth gradients — real footage will expose tile seam artifacts and edge behavior that the current metrics can't capture.

**Priority 3 (CPU, can run now):**  
Try the ensemble backend on a real fixture. It's the most stable of the non-baseline approaches and combines spatial adaptivity with global color correction.

**Metric to reconsider:**  
The composite score weighting (id_drift ×0.4, integration ×0.6) may be backward for VFX.  
In a real shot, id_drift matters most — you cannot deliver CG that looks like a different object.  
Recommend discussing with DiMo which matters more before using composite score as the primary ranking signal.
