# Phase 2 Historical Known-Fail List

Explicit, committed list of known failure modes and limitations from the
pre-reset Phase 2 sweeps (last consolidated 2026-06-07). "Known-fail" here
means: observed limitation preserved with evidence, not a silent gap. The
current Phase 2 pass gate is `PHASE2_GATE.md`.

## Backend / quality

1. **PCT-Net over-moves identity on aggressive relights.**
   Highest `fg_delta_mean` (0.555) in the GPU sweep. Strong integration but the largest
   perceptual movement of the CG foreground — risk for hero assets where identity must hold.
   Evidence: `PHASE2_SCORING.md` GPU table row 11. Disposition: keep as a candidate, but
   identity-preservation weighting must be resolved before it is a default.

2. **IC Flux relight deviates hard from the plate.**
   `mean_err_vs_plate` 0.714 — by far the highest. Produces large lighting change but pulls
   away from plate consistency. Evidence: `runs/overnight_harmonic_sweep/ic_flux/scores.json`.
   Disposition: parallel/experimental lane only, not a baseline for the gate.

3. **IC Flux runtime is dependency-fragile.**
   The `ic-flux/cuda121-v1` runtime is pinned to torch 2.5.1+cu121; unpinned `transformers`
   /`xformers` repeatedly broke clean rebuilds (`ncclCommResume`, `torch.float8_e8m0fnu`).
   Fixed in releases v20 (xformers→torch-2.12) and v21 (`transformers<5`, `huggingface_hub<1`).
   Disposition: fixed and pinned; flagged so future edits keep the caps.

## Evaluation coverage

4. **Input-case variety is below the 10-case bar.**
   Only 2 still fixtures (`golden_synthetic_001`, `compositingpro_sh009_minimal`) + 1 proxy
   sequence exist. Technique breadth is met; input-case breadth is not.
   Disposition: blocked on issue #3. DiMo needs to rule on the CC0
   panorama-crop L1 path or supply real plates/footage plus matched HDRI. The
   immediate intake tranche is 5 validator-clean photographic cases; final
   Phase 2 still requires the locked 10-20 case eval set in `PHASE2_GATE.md`.

5. **Synthetic rankings do not transfer to real footage.**
   Synthetic CPU winner `local_spatial 4×4` ≠ real-fixture winner `rgb_affine`. Synthetic
   fixtures must not be used to pick a production default. Evidence: `PHASE2_SCORING.md` CPU tables.

6. **Sequence flicker test is not optical-flow-aligned.**
   `evaluate_sequence_flicker.py` reports raw frame-to-frame temporal RMSE, not motion-compensated
   coherence. A clean number here does not guarantee temporal stability under real motion.
   Disposition: acceptable as a first flicker read; flow-aligned metric is future work.

## Metric / process

7. **Composite-score weighting is unresolved.**
   CPU composite weights integration 60% / identity 40%, which may be backwards for hero CG.
   GPU and CPU metric families differ and cannot be merged into one ranking.
   Disposition: open product decision; do not present a single unified "winner" until settled.

8. **Some raw CPU artifacts are absent from this checkout.**
   Bert's synthetic CPU Round 1/2 raw JSON summaries are not in this checkout; those rows are
   sourced from `runs/overnight_20260530/HANDOFF.md`. Disposition: values trusted via handoff,
   raw JSON to be re-attached if a re-audit is needed.
