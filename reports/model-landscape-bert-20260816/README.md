# Bert model/tool scan — 2026-08-16

Scope: alternatives to IC-Light FBC after sh009 exposed the identity-versus-strength failure. This is desk research; every candidate remains unproven until run against the project contract.

## Revised verdict after cross-check

The next experiment has two parallel lanes:

1. **Backend bakeoff:** IC-Light FBC control versus DreamLight SD1.5, then DreamLight FLUX only if it fits the 11.6 GiB card. DreamLight is the first runnable challenger because it accepts foreground/background inputs, publishes code and weights under Apache-2.0, and its Spectral Foreground Fixer explicitly targets foreground appearance consistency.
2. **Intake unblock:** evaluate DiffusionLight's plate-derived HDRI against the existing hand-matched sh009 HDRI. A backend win on sh009 remains one case; Layer 2 still requires the real-plate tranche with at least two `camera_original` cases.

Round two:

- NVIDIA Harmonizer: technically interesting single-step Cosmos 0.6B architecture, but its Omniverse NuRec/driving-simulator domain makes transfer to a forest VFX creature a substantial risk.
- Adobe Harmonize API beta: closed quality oracle for non-sensitive practice material, subject to privacy and foreground-only-output limitations.

Watch list:

- LooseRoPE: best conceptual match. It explicitly frames Neglect and Suppression as endpoints of one attention tradeoff, matching the conservative and raw sh009 failures. No runnable release was found, and its Flux Kontext full-frame contract conflicts with `plate_untouched` unless the result is reconstructed strictly through the authorized matte.
- LiMo: promising plate-derived spatiotemporal lighting estimation, with no runnable release found.
- Consistent Feature Transport, UniRelight, IMPRINT, and LightLab: relevant research, but each currently has a release, domain, compute, or output-contract mismatch for the immediate test.

Excluded from the execution slate:

- `nishitanand/image-relighting-diffusion`: no declared license was found, so a successful result would still be unusable for release.
- General full-frame editors such as FLUX.2, Qwen-Image-Edit, and Nano Banana Pro: useful only as visual ceilings because their native output contract violates locked `plate_untouched` requirements.

## Scoring declared before execution

All candidates receive identical sh009 foreground, plate, alpha, crop, resolution, and seed policy. Review uses randomized candidate labels and keeps the method fixed before outputs are seen.

Hard eligibility checks:

- Reconstruct the deliverable as original plate plus masked adjusted foreground.
- Outside-alpha plate delta must meet the existing Layer-1 threshold.
- Bark topology, ember placement, silhouette, alpha edges, and authorized-region boundaries must remain intact. Any visible identity/topology mutation receives zero production credit.

Measurements reported separately rather than collapsed into one opaque score:

- masked LPIPS and DINO similarity for bark and ember regions;
- edge/matte error and maximum/RMS plate delta outside alpha;
- peak VRAM and runtime;
- blind human A/B preference against raw A-over-B for integration quality.

Decision rule:

- A candidate must clear every hard eligibility check before preference votes count.
- On sh009, a candidate advances only if it is preferred to raw A-over-B and improves on the IC-Light control without worse identity measurements.
- Advancement is a backend result, not a Layer-2 pass. Layer 2 remains governed by `PHASE2_GATE.md`, including the required real-plate set and at least two `camera_original` cases.

## Primary sources

- DreamLight: https://github.com/yongliu20/DreamLight
- DreamLight weights: https://huggingface.co/LYAWWH/DreamLight
- LooseRoPE: https://snap-research.github.io/LooseRoPE/
- NVIDIA Harmonizer: https://github.com/NVIDIA/harmonizer
- Adobe Harmonize API beta: https://developer.adobe.com/firefly-services/firefly-photoshop-beta/
- DiffusionLight: https://github.com/DiffusionLight/DiffusionLight
- UniRelight: https://github.com/nv-tlabs/UniRelight
