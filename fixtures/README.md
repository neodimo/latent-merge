# Fixtures — Provenance (enforces LOCKED L1)

`plate_provenance` is the gate-eligibility flag. Only `photographic` feeds the quality (Layer-2) gate.

- `compositingpro_sh009_minimal` — photographic. Real RAW footage plate + CG monster. The anchor real-plate case.
- `smoke_blender_set` — `blender_smoke`. Unsplash photos + Poly Haven HDRI + Blender EEVEE comp. The plate is Blender-mediated, not pristine photography. Does NOT satisfy L1. Plumbing/smoke only.
- `golden_synthetic_001` — synthetic. Smoke harness only.
- `synthetic_sequence_001` — synthetic. Flicker plumbing only.

Do not place a non-`photographic` fixture in any "validation"/PASS table without the SMOKE-ONLY label.
