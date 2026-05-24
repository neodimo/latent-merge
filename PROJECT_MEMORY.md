# Latent Merge Project Memory

Project channel: `#latent-merge` planned.
Origin: Discord `#project-planning`, 2026-05-20.
People/agents involved so far: DiMo, Gonzo, Bert, Claude Bot research passes.

## Goal

Build a Nuke node/tool that acts like a smarter Merge for VFX integration:

```
CG RGBA + plate + alpha/matte -> background-conditioned relight/harmonize -> adjusted CG only -> normal over original plate
```

The plate must remain untouched except for explicit, inspectable interaction passes such as contact shadows, edge spill, or shadow/reflection contributions. The tool should not output an AI-repainted composite as its primary result.

First target: a low-resolution still/short-sequence prototype proving that A-over-B integration improves while preserving CG identity.

Long-term target: production-capable Nuke workflow for image sequences, 4K+, 16-bit/HDR, ACEScg/linear EXR, with temporal stability and artist controls.

## Current Consensus

- The right v0 is not a fully automatic magic compositor. It is a foreground-preserving harmonization/relighting tool.
- Start aggressively at 512-1024px crops/proxies to get visual signal fast.
- Test image sequences early at low resolution so flicker risks are visible from the beginning.
- Do not train a new model from scratch first. Run an offline model bakeoff using existing models/graphs, then localize the winner into a Nuke-facing service.
- ComfyUI cloud is useful for the bakeoff as long as every graph is designed around localizable inputs/outputs.
- Nuke implementation should likely start as a gizmo/Python node talking to a local Python/PyTorch inference service. Do not fight embedded Nuke Python/CUDA packaging before model behavior is proven.

## Phase 0 Progress - 2026-05-24

- Gonzo created a deterministic local smoke harness at `scripts/smoke_pipeline.py`.
- Generated synthetic golden fixture: `fixtures/golden_synthetic_001/plate_rgb.png`, `cg_rgba.png`, `alpha.png`, `fixture.json`.
- Smoke run writes: `runs/phase0_smoke/adjusted_fg.png`, `final_comp.png`, `delta.png`, `alpha_weighted_delta.png`, `alpha_used.png`, `job.json`.
- The Phase 0 transform is intentionally a stub: conservative alpha-weighted RGB mean match. It proves executable file flow and diagnostics only.
- Local GitHub CLI auth is currently invalid for `neodimo`, so pushing/cloning the actual GitHub repo needs Bert/DiMo or a refreshed token.

## Transformer / Latent Model Position

DiMo's coworker suggested a transformer latent based model as the best conceptual direction.

Gonzo/Bert consensus:

- Directionally correct for the serious long-term version.
- A transformer/diffusion backbone can condition on foreground, plate, alpha, and optional AOVs while reasoning globally about lighting/color context.
- Latent-space processing can be efficient and expressive, but naive latent alpha compositing is not pixel-equivalent. Soft edges, semi-transparent pixels, motion blur, defocus, and fine plate detail can break.
- A DecFormer / pixel-equivalent latent compositing direction is especially relevant because it tries to make latent compositing respect pixel-space A-over-B math.
- First proof should still be practical: test existing relight/harmonize models before building a custom transformer latent architecture.

Likely architecture direction:

```
latent encoder
  -> transformer/DiT conditioned on CG + plate + alpha + optional AOVs
  -> adjusted foreground latent
  -> decode adjusted CG
  -> trusted Nuke A-over-B composite over untouched plate
```

## Debug Outputs / Trust Requirements

The Nuke node should expose:

- final comp
- adjusted foreground
- delta
- alpha-weighted delta
- confidence/diagnostic matte
- interaction/shadow pass if generated
- optional pre/post color-space diagnostics

Artists must be able to inspect what changed. The reviewable contract is: the model modifies A and optional interaction passes, not B.

## Inputs

Minimum:

- A: CG RGBA
- B: live-action plate RGB
- alpha/matte

Useful optional inputs:

- depth
- normals
- cryptomatte/object ID
- diffuse/specular/direct/indirect AOVs
- roughness/metalness
- motion vectors
- shadow catcher/contact matte
- camera/lens metadata where available

## Main Risks

- Diffusion rewriting CG texture, geometry, logos, or fine identity details.
- VAE encode/decode distortion.
- Alpha edge seams, halos, defocus/motion-blur mistakes.
- Linear EXR / ACEScg / HDR mismatch with SDR-trained image models.
- Grain, lens response, blur, and chromatic/fringe differences.
- Temporal flicker across image sequences.
- Public harmonization datasets are mostly photo/photo, not render/plate; CG-domain fine-tuning data may be needed.
- 4K+ production performance will require tiling, crops, caching, and probably better hardware/infrastructure.

## Aggressive Timeline

Aggressive v0, 1-2 weeks:

- Offline still-frame bakeoff outside Nuke.
- Use ComfyUI cloud and/or local Python harness.
- Inputs: CG RGBA, plate, alpha; optional AOVs if easy.
- Outputs: adjusted CG, final comp, delta/debug passes.
- Resolution: 512-1024px crops/proxies.
- Judge: identity preservation, integration improvement, plate untouched.

Aggressive v1, 3-6 weeks:

- First Nuke-facing prototype via local inference service.
- Nuke sends A/B/alpha crop frames; service returns adjusted foreground.
- Nuke does the trusted normal over B.
- Include debug passes and basic knobs.
- Short image-sequence support can start here as proxy/experimental.

Temporal tests, week 4-8:

- deterministic seeds/settings
- consistent crop/window normalization
- previous-frame guidance or optical-flow warping
- delta/flicker diagnostics
- proxy image sequence tests before production claims

Production quality ladder:

- 4K+/16-bit/HDR/ACEScg/linear EXR
- tiling/crop stitching
- identity-preserving adapters/LoRAs
- temporal model or stabilizer
- grain/lens/defocus/edge/contact shadow handling
- production installer/runtime packaging

Longer-term estimates discussed:

- 2-3 months: useful still-frame internal alpha if model bakeoff works.
- 5-8 months: sequence-capable prototype with temporal stabilization.
- 9-18+ months: credible production-grade tool depending heavily on data quality and temporal/EXR handling.
