# Latent Merge — LOCKED Constraints (read FIRST, every session)

Omid's non-negotiables. If a fixture, run, gate, or report violates one, it does not count and must not be presented as progress. Re-read before any work in this project. This file outranks every other doc here.

## L1 — Real photographic plates only (2026-06-12, re-affirmed 2026-06-17)

The plate (B) must be real-life photography. A Blender/CG layout rendered and called a "plate" is NOT acceptable. CG (A) is inserted INTO the photograph, HDRI/matched-light lit, casting real shadow interaction, with segmentation-level matte/holdout where plate foreground overlaps CG. The plate pixels stay the untouched photograph — never an EEVEE/Cycles re-render of it.

- A fixture counts toward the quality gate only if `plate_provenance == "photographic"`.
- Blender-mediated plates are SMOKE-ONLY: they exercise plumbing, never quality. Name them `smoke_*`, never `real_*`.

## L2 — Modify A, never B

Output is adjusted foreground over the original plate, plus inspectable interaction passes (contact shadow, edge spill). No opaque AI-repainted composite as the primary result. `plate_untouched` is a hard, non-negotiable gate.

## L3 — Preference over baseline, not beauty

A result passes Layer 2 only if a human prefers it over raw A-over-B on real plates. A Layer-1 (plumbing) PASS on synthetic/Blender data is NOT a quality result and must never be reported as one.

## L4 — Identity preserved

CG texture, geometry, logos, fine detail must survive. Relight/harmonize — do not repaint the asset.

## Anchor case

`fixtures/compositingpro_sh009_minimal` is currently the ONLY real-plate case (real RAW footage + CG monster). Build the rest like sh009, not like `smoke_blender_set`.
