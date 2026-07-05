# Phase 2 Evaluation Gate — Definition

This is the formal definition of what "Phase 2 passed" means. It replaces the
earlier implicit assumption that a technique sweep with proxy metrics was an
evaluation. Operational readiness (pipeline/UI/runtime work) is necessary but
**not** sufficient: a result must also be *rejected if it breaks trust* and
*preferred by a human over doing nothing* before Phase 2 is passed.

The gate has two layers. A result must clear Layer 1 to be eligible for Layer 2.

## Layer 1 — Automated hard-rejection checks (Gonzo lane)

Objective, scriptable pass/fail gates. No human judgment. Implemented in
`scripts/phase2_rejection_checks.py`, thresholds in `configs/phase2_gate.json`.

| Check | What it proves | Default threshold |
|-------|----------------|-------------------|
| `gate_evidence_complete` | Required baseline and runtime evidence exists; incomplete legacy jobs cannot pass by omission. | zero missing fields |
| `plate_untouched` | Outside the matte, the final comp equals the original plate (core trust contract). | max abs delta ≤ 0.012 (~3/255) |
| `edge_seam` | The matte edge gains no halo/ringing beyond the raw A-over-B composite. | edge-gradient ratio ≤ 1.25 |
| `runtime_duration_s` | Runs within a usable time budget. | ≤ 30 s |
| `runtime_process_rss_mb` | Stays within host memory. | ≤ 11000 MB |
| `runtime_reserved_vram_mb` | Stays within GPU memory (CUDA runs only). | ≤ 11000 MB |
| `flicker_final_comp_rmse` | Sequence cases: no catastrophic frame-to-frame flicker. | max temporal RMSE ≤ 0.05 |

`plate_untouched` failure (or `contract.plate_repainted == true`) is a
**trust-contract violation** — an automatic, non-negotiable fail regardless of
how good the result looks.

Run:

```bash
PYTHONPATH=".deps:." python3 scripts/phase2_rejection_checks.py \
    --job runs/<case>/job.json \
    [--sequence-metrics runs/<case>/sequence_metrics.json]
```

Writes `rejection_checks.json` with per-check value/threshold/pass and an
`overall_pass` / `trust_contract_violation` summary.

## Layer 2 — Blind A/B visual scoring (Bert lane)

Only results that clear Layer 1 proceed. For each case, a reviewer sees
**randomized** before/after pairs (raw A-over-B vs adjusted final comp) without
knowing which is which, and scores a 1–5 rubric per category:

- lighting direction & intensity match
- color / white-balance match
- contrast / black-level match
- edge / contact integration
- identity preservation
- overall preference

Rules: comments required for any score of 1–2; record whether the adjusted
result is **better, equal, or worse** than raw A-over-B. Rubric + scoring
harness are Bert-owned; the still inputs come from
`scripts/phase2_contact_sheet.py`, temporal cases from a Discord-viewable MP4
rendered by `scripts/phase2_sequence_video.py`.

## Gate pass criteria

Scored **per backend** (PCT-Net and IC Flux do not share a scorecard;
operational success does not let either pass visually):

1. **Zero trust-contract violations** across the eval set (Layer 1). Hard stop.
2. **≥ 70%** of cases preferred over raw A-over-B (Layer 2 "better").
3. **≤ 10%** of cases materially worse than raw A-over-B.
4. **Acceptable sequence flicker** on every sequence case (Layer 1).

Average "beauty" is explicitly **not** the metric — preference-vs-baseline and
trust safety are.

## Locked evaluation set

- 10–20 representative CG-over-plate cases, frozen (fixtures + matte), provided by DiMo.
- At least one short proxy sequence for flicker.
- Standardized contact sheets generated per backend for the blind session.
- Standardized sequence review videos generated for temporal/flicker review.

## Artifact reporting policy

Scoring and status updates must show representative case variety, not just the
`golden_synthetic_001` toy fixture. Use the Blender reference cases and real
plate/CG/alpha fixtures as the primary visual evidence, with before/after stills
or contact sheets spanning multiple case types. The synthetic sphere/oval fixture
is acceptable as a quick file-flow or Layer-1 regression sentinel, but it should
not be the recurring headline artifact for visual-quality updates.

## Current status (2026-07-05)

- ✅ Layer 1 rejection tooling exists and fails closed on malformed,
  duplicate, or non-photographic intake.
- ✅ Contact-sheet tooling, proxy sequence flicker metrics, and sequence
  review video tooling exist for eligible cases.
- ✅ Photographic fixture intake validation is implemented in
  `scripts/validate_photographic_fixtures.py`.
- ✅ The proposed CC0 panorama path has a proven end-to-end L1 toolchain:
  `pano_to_plate.py` -> `render_cg_insert.py` -> `assemble_fixture.py` ->
  `validate_photographic_fixtures.py`, with the matched-HDRI CG insert proof in
  `reports/cg-insert-matched-hdri-20260627/`.
- ⬜ Intake tranche is still blocked at 1/5 unique photographic fixtures:
  `fixtures/compositingpro_sh009_minimal` is the only accepted anchor case.
- ⬜ Layer 2 blind scoring cannot honestly start until the intake tranche is
  populated with real photographic plates.
- ⬜ Final Phase 2 pass still requires the locked 10-20 case eval set plus at
  least one short sequence.

**Gate state: defined, Layer 1 ready, not yet passed.** Today's concrete gate
is still DiMo's YES/NO ruling on whether a rectilinear crop of a CC0
equirectangular photo-panorama counts as a real photographic plate under L1.
YES lets Gonzo produce the 5-case intake set immediately with the proven chain;
NO means DiMo needs to supply real footage or plates plus matched HDRI.
