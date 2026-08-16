# Model / Tool Landscape Scan — 2026-08-16 (Gonzo)

DiMo asked both agents to scan for newer models and tools that would beat what
this project currently uses. This is desk research only: **nothing below has been
run, benchmarked, or verified on our hardware.** Every claim is sourced from the
project page, repo README, or paper listed with it. Treat "runs on our box" as an
untested inference wherever it appears.

## What we currently use

- **Relight backend:** IC-Light SD1.5 FBC (`lllyasviel/IC-Light`, 2024). First
  real-plate inference 2026-08-16 — plumbing works, quality failed: raw model
  output destroys the monster (LOCKED L4), conservative transfer is
  indistinguishable from raw A-over-B (LOCKED L3).
- **Harmonization baseline:** PCT-Net (2023), AICT as a color-science lane.
- **Plate lighting:** hand-matched CC0 equirectangular panoramas, gnomonic crop,
  Blender relight. Proven on exactly one panorama; a four-panorama tranche on
  2026-08-13 found no azimuth minimum on any of them.
- **Interaction:** Blender ground proxy + shadow catcher, object-on/off ratio
  difference pass.

## Ranked findings

### 1. DiffusionLight / LiMo — attacks our actual bottleneck, not our backend

The matched-panorama toolchain is the thing that is provably not generalising.
Both of these estimate an HDR environment map **from the plate photograph
itself**, which would make the panorama-matching step unnecessary and turn any
camera-original photo into a valid L1 plate.

- **DiffusionLight** (CVPR 2024, <https://github.com/DiffusionLight/DiffusionLight>,
  <https://diffusionlight.github.io/>) — paints a chrome ball into the image with
  an SDXL LoRA + depth inpainting, brackets exposures, converts to an HDRI. Code
  and weights released. Available today.
- **LiMo** (CVPR 2026, Eyeline Labs / Bolduc, Philip, Ma, He, Debevec, Lalonde,
  <https://eyeline-labs.github.io/LiMo/>) — spatiotemporal successor. Generates
  mirror + diffuse spheres at multiple exposures for a **specified 3D target
  position**, conditioned on depth plus novel distance/direction-to-target maps,
  then fuses to one HDRI via differentiable rendering. Explicitly aimed at
  virtual object insertion and virtual production. **No code link found on the
  project page** — watch-list, not adoptable.
- Also seen: "HDR Environment Map Estimation with Latent Diffusion Models"
  (<https://arxiv.org/abs/2507.21261>), addresses ERP pole distortion and seams.

**Why this ranks first:** it changes the intake economics. Intake is 1/5 and the
Layer-2 gate needs >= 2 `camera_original` cases. Estimating light from the plate
removes the requirement to find a photograph whose matching panorama exists.

### 2. SpotLight — the best structural fit to the pipeline we already built

<https://github.com/lvsn/SpotLight>, <https://arxiv.org/abs/2411.18665>

Training-free. The user supplies the **desired shadow of the inserted object**;
SpotLight reshades the object to be consistent with that shadow and harmonises it
into the background. It rides on one of two open diffusion renderers conditioned
on 2D intrinsic maps: **ZeroComp** (weights on the Laval S3, trained on OpenRooms
and InteriorVerse) or **RGB↔X** (Zeng et al. 2024). Post-processing uses
background preservation, colour rebalancing, and OpenImageDenoise.

We already render exactly the control signal it wants — the Blender ground proxy
plus difference pass produces the object's cast shadow.

Honest risks:

- The repo pins **Blender 4.0 or 4.1**, and states 4.2+ is unsupported due to
  EEVEE changes. We are well past that; we would have to feed our own shadow
  renders instead of using their generator.
- ZeroComp checkpoints are trained on **indoor synthetic** datasets (OpenRooms,
  InteriorVerse). `sh009` is outdoor. Generalisation is unproven for our case.
- It is still a generative repaint of the object region, so LOCKED L4 identity
  preservation is exactly as much of an open question as it was with IC-Light.
- Depends on Depth-Anything-V2 / ZoeDepth / MiDaS for background geometry.

### 3. DiffusionRenderer — de-light/re-light with real G-buffer estimation

<https://github.com/nv-tlabs/diffusion-renderer> (CVPR'25 Oral),
Cosmos version at <https://github.com/nv-tlabs/cosmos-transfer1-diffusion-renderer>.

Joint inverse renderer (estimates geometry/material buffers from real video) and
forward renderer (synthesises under specified lighting). Object insertion is a
listed application. Two tiers of weights are public:

- **Academic SVD version** (`nexuslrf/diffusion_renderer-inverse-svd`,
  `-forward-svd`, `-forward-svd-objaverse`) — SVD-scale backbone; plausibly fits
  12 GB at low resolution. **Untested on our box.**
- **Cosmos 7B** (`nvidia/Diffusion_Renderer_Inverse_Cosmos_7B` and `_Forward_`)
  — higher quality, will not fit the 3080 Ti's 11.6 GiB.

The inverse renderer is independently interesting: it would give us a measured
albedo/normal/roughness estimate of the plate, which is currently something we
assume rather than measure.

### 4. Watch-list, no adoptable artifact found

- **UniRelight** (NVIDIA, <https://research.nvidia.com/labs/toronto-ai/UniRelight/>)
  — jointly predicts relit output and albedo in one pass with a video DiT; claims
  to beat DiffusionRenderer, especially on anisotropic/glass/transparent
  materials.
  **Correction (2026-08-16, mine):** I first wrote "no weights/code link" because
  the project page carries none. That was an error of method — absence of a link
  on a project page is not absence of a repo. `nv-tlabs/UniRelight` exists and
  was pushed 2026-04-08. Its license is **NOASSERTION**, which is the same
  licensing defect I used to exclude `nishitanand/image-relighting-diffusion`
  from the slate; the exclusion argument applies to UniRelight equally if it is
  ever promoted from the watch list.
- **MV-CoLight** (<https://arxiv.org/html/2505.21483v1>) — object compositing with
  consistent lighting, claims SOTA on standard benchmarks.
- **DreamLight** (<https://openreview.net/forum?id=y2wt5c1Uhu>) — already in
  `REFERENCES.md`; still no verified open weights.
- **LightCtrl** (ICLR 2026, <https://github.com/GVCLab/LightCtrl>) and
  **FlowPortal** (CVPR 2026, training-free video relight + background
  replacement) — video lane, not our current single-frame problem.

### 5. Explicitly not recommended

FLUX.2 / FLUX.1 Kontext, Qwen-Image-Edit (20B), Nano Banana Pro. These are the
loudest models of 2026 and they are the wrong tool here: they repaint the whole
frame, which is a direct **LOCKED L2** violation, and none of them can promise
`plate_untouched`. Their only legitimate use in this project is as an
upper-bound reference for what a great composite looks like — never a shipping
path.

## Hardware ceiling (DiMo decision, not mine)

11.6 GiB usable on the RTX 3080 Ti puts the Cosmos 7B tier, FLUX.2, and the 20B
editors out of reach locally. Everything ranked 1–3 above is chosen partly
because it plausibly fits. If DiMo wants the top tier, that is a hardware or
cloud-spend decision.

## Cross-check of Bert's parallel scan (verified 2026-08-16 ~10:20 PDT)

Bert posted a competing candidate list. I verified each artifact rather than
taking it on trust. **All four repos exist.** Verification detail:

| Candidate | Verified | Notes |
|---|---|---|
| DreamLight (`yongliu20/DreamLight`) | ✅ Apache-2.0, 396 stars | Weights **genuinely published** at `huggingface.co/LYAWWH/DreamLight` for both FLUX and SD1.5. Repo last pushed **2025-07-14**; arXiv 2506.14549 is a 2025 paper. |
| NVIDIA Harmonizer (`NVIDIA/harmonizer`) | ✅ Apache-2.0, 58 stars, pushed 2026-07-30 | Description is explicit: harmonizes **Omniverse NuRec renderings**. That is the driving-sim / neural-reconstruction domain. |
| Open Illumination Control (`nishitanand/image-relighting-diffusion`) | ⚠️ exists, **1 star, license NOASSERTION** | No license means it cannot enter anything we release. |
| LooseRoPE (`snap-research.github.io/LooseRoPE/`) | ✅ SIGGRAPH 2026, page live | Training-free. Confirmed: it names **Neglect** and **Suppression** as the two failure modes, built on Flux Kontext. No code release found. |

**The DreamLight finding supersedes our own docs.** `REFERENCES.md` currently
lists DreamLight as "candidate if code/weights are available". They are
available, under Apache-2.0, for both backbones. That line is stale and should
be corrected. Credit to Bert's lane for catching it.

**LooseRoPE is a genuinely exact diagnosis of our 2026-08-16 result.** Its two
named failure modes map one-to-one onto what sh009 produced: the conservative
detail transfer is *Neglect*, the raw model foreground is *Suppression*. It
argues these are two ends of one attention-field-of-view axis rather than two
separate bugs, which reframes "tune the transfer strength" as travelling a
tradeoff curve rather than hunting a fix. Caveat: it operates on Flux Kontext,
a full-frame editor, so the LOCKED L2 `plate_untouched` question applies to it
exactly as it does to the models I rejected in section 5.

Where I disagree with Bert's ranking:

- **Drop the 1-star repo from the bakeoff.** Unlicensed code cannot reach the
  release gate described in `AUTOMATION.md`, so a win there would be unusable.
- **NVIDIA Harmonizer is a bigger domain jump than "the question".** It is
  purpose-built for reinserted assets in Omniverse NuRec scenes. sh009 is a VFX
  creature on a forest plate. Bert flagged the transfer risk himself; I would
  rank it below DreamLight and treat it as a second-round entrant.
- **A four-way bakeoff on one plate cannot close Layer 2.** L3 requires human
  preference over raw on real plates, and our own gate requires >= 2
  `camera_original` cases. Even a decisive DreamLight win on sh009 is n=1. The
  backend bakeoff and the intake problem are independent lanes and intake is the
  one gating the gate.
- **Declare the scoring method before running the bakeoff.** Four outputs judged
  by eye afterwards is how we pick a favourite instead of measuring a winner —
  and the 2026-08-15 sharpness/grain work is a written record of an instrument
  that produced confident, wrong numbers twice before it earned trust.

**Bookkeeping:** Bert's `projects/latent-merge/RESEARCH_2026-08-16.md` does not
exist in this checkout and is not in `origin` (fetched and searched, HEAD is
`4d6ce9c`). By our own task-completion contract that note is not durable yet —
it lives only on his VPS. Flagging, not fixing; the file is his to push.

## Recommended next bounded experiment

Run **DiffusionLight on the `sh009` plate** and compare the estimated HDRI
against the HDRI we currently hand-match, using the existing projection-convention
evidence in `reports/projection-convention-fix-20260814/` as the reference frame.
It is the cheapest of the three, it is fully released, and it attacks the
blocker that has actually stalled intake rather than the backend that merely
disappointed us yesterday.
