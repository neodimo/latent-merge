# References

## Primary Practical Candidates

- PCT-Net: lightweight full-resolution pixel-wise color transform harmonization; pragmatic, less hallucination-prone baseline and current first implementation target.
- AICT: high-resolution adaptive 3D LUT/color transformation; relevant for VFX-style color-science trust and current first implementation target.
- IC-Light / IC-Light V2 / FLUX-style background-conditioned foreground relighting: strong alternate prototype path if accessible through ComfyUI/cloud/fal.ai, but keep as second lane until the PCT-Net/AICT baseline is wired.
- DiffHarmony / DiffHarmony++ / Harmony-VAE: latent diffusion harmonization and VAE distortion references.
- ControlCom: controllable composition/harmonization baseline.
- Video Triplet Transformer: useful reference for temporal video harmonization.
- DecFormer / pixel-equivalent latent compositing: important long-term research line for mask/edge correctness.
- CFDiffusion / foreground relighting and shadow generation methods: possible path for contact shadows/interactions.
- DreamLight: runnable Apache-2.0 candidate with published SD1.5 and FLUX code/weights; its Spectral Foreground Fixer targets foreground appearance consistency. Repository: https://github.com/yongliu20/DreamLight; weights: https://huggingface.co/LYAWWH/DreamLight.
- Photorealistic Object Insertion with Diffusion-Guided Inverse Rendering: longer-term physically grounded relighting reference.

## Commercial Baseline

- Beeble SwitchLight / Beeble Studio, especially Nuke-facing workflow, EXR/HDR handling, and relighting quality bar.

## Research Links Mentioned

- PCT-Net: https://github.com/rakutentech/PCT-Net-Image-Harmonization/
- AICT: https://openreview.net/forum?id=jXgHEwtXs8
- DiffHarmony: https://github.com/nicecv/DiffHarmony
- Video Triplet Transformer: https://github.com/zhenglab/VideoTripletTransformer
- Diffusion-Guided Inverse Rendering: https://arxiv.org/abs/2408.09702

## Current Fixture Source

- Compositing Pro free Nuke CG compositing tutorial files: https://www.compositingpro.com/free_nuke-cg_compositing_tutorial_files/
  - Published as a free single-frame CG render and plate for practice.
  - License note on the source page: personal practice only, not commercial use.
  - Phase 1 should use only plate + CG creature foreground + alpha.

## IC-Light V2 / FLUX Notes

- Official IC-Light repo: https://github.com/lllyasviel/IC-Light
  - Apache-2.0 repo.
  - Current open repo documents SD1.5 text-conditioned and background-conditioned relighting models.
  - The repo explicitly lists text-conditioned and background-conditioned models taking foreground images as inputs.
- IC-Light V2 / FLUX:
  - The current V2 path appears to be primarily online/API/Space based rather than a fully open local model path.
  - ComfyUI/fal.ai wrappers exist and may be useful for bakeoff, but this should be treated as cloud/API evaluation until local weights and license terms are confirmed.
  - Non-commercial/license restrictions have been reported for V2 workflows, so do not select it for packaging until the exact model/license is verified.
