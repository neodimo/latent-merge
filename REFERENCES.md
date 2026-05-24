# References

## Primary Practical Candidates

- IC-Light / IC-Light V2 / FLUX-style background-conditioned foreground relighting: fastest first prototype path if accessible; likely useful through ComfyUI/cloud.
- DiffHarmony / DiffHarmony++ / Harmony-VAE: latent diffusion harmonization and VAE distortion references.
- PCT-Net: lightweight full-resolution pixel-wise color transform harmonization; pragmatic, less hallucination-prone baseline.
- AICT: high-resolution adaptive 3D LUT/color transformation; relevant for VFX-style color-science trust.
- ControlCom: controllable composition/harmonization baseline.
- Video Triplet Transformer: useful reference for temporal video harmonization.
- DecFormer / pixel-equivalent latent compositing: important long-term research line for mask/edge correctness.
- CFDiffusion / foreground relighting and shadow generation methods: possible path for contact shadows/interactions.
- DreamLight: candidate if code/weights are available; reportedly focused on identity drift and color bleeding.
- Photorealistic Object Insertion with Diffusion-Guided Inverse Rendering: longer-term physically grounded relighting reference.

## Commercial Baseline

- Beeble SwitchLight / Beeble Studio, especially Nuke-facing workflow, EXR/HDR handling, and relighting quality bar.

## Research Links Mentioned

- PCT-Net: https://github.com/rakutentech/PCT-Net-Image-Harmonization/
- AICT: https://openreview.net/forum?id=jXgHEwtXs8
- DiffHarmony: https://github.com/nicecv/DiffHarmony
- Video Triplet Transformer: https://github.com/zhenglab/VideoTripletTransformer
- Diffusion-Guided Inverse Rendering: https://arxiv.org/abs/2408.09702
