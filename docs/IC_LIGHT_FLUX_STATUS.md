# IC-Light / Flux Backend Status

Last updated: 2026-06-10

## Decision

Do not treat the current IC-Light / Flux scripts as passing harmonization
backends.

The Blender eval cases are the current visual reference set. In the horse,
duck, and cat cases, the SD1.5 IC-Light FC runner produced clipped,
psychedelic, non-integrated foregrounds. The outputs are worse than raw
A-over-B against the Blender `target.png` references, so these artifacts are
diagnostics, not evidence of backend readiness.

## What Failed

Runs inspected:

- `runs/ic_light_blender_case02_horse_noon`
- `runs/ic_light_blender_case03_duck_neon`
- `runs/ic_light_blender_case04_cat_neon`

Layer-1 result:

- `plate_untouched` passed because the final composite preserved the plate
  outside the matte.
- `edge_seam` failed on all three cases.
- Runtime RSS passed only after the GPU/diffusion ceiling was raised to
  11000 MB.

Target-reference check:

- `horse_noon`: raw foreground RMSE 0.27172, IC foreground RMSE 0.59481
- `duck_neon`: raw foreground RMSE 0.23835, IC foreground RMSE 0.37660
- `cat_neon`: raw foreground RMSE 0.23906, IC foreground RMSE 0.68643

Diagnostic artifact:

- `runs/ic_light_failure_diagnostic.png`
- `runs/ic_light_failure_metrics.json`

## Likely Causes

The current `scripts/run_ic_flux.py` path is an SD1.5 IC-Light foreground
conditioning experiment. It feeds the isolated CG foreground into IC-Light and
uses the plate only indirectly through text prompts before compositing the
generated result over the plate. That is not enough conditioning for
CG-over-plate harmonization and behaves like a generative relight rather than a
controlled adjustment.

The older `scripts/ic_flux_runner.py` path assumes an IC-Light-on-FLUX
ControlNet package exists locally. That path remains speculative until real,
compatible weights and an officially supported inference recipe are verified.

## Current Policy

- Keep the GPU/diffusion RSS ceiling at 11000 MB.
- The CLI path in `scripts/run_ic_flux.py` now defaults to the official
  SD1.5 background-conditioned `iclight_sd15_fbc` workflow: 12-channel UNet,
  foreground+background VAE concat conditioning, grey-matted foreground outside
  alpha, and the official highres-denoise pass.
- The raw generated IC-Light foreground is not trusted directly. The CLI
  postprocesses it as a low-frequency lighting estimate and transfers that
  lighting back onto the original CG. The default transfer is conservative:
  it preserves original detail and does not brighten above the source
  low-frequency luma unless `--transfer-ratio-max` is raised.
- The `iclight_sd15_fc` path remains selectable with `--ic-model fc`, but it is
  diagnostic only for CG-over-plate work.
- Do not promote IC-Light/Flux results into Phase 2 evidence unless they pass
  Layer 1 and beat raw A-over-B on the Blender target references.
- Use the Blender `target.png` references as the sanity check for synthetic
  fixture development.
- Treat the present IC-Light outputs as failed diagnostics.

## Research Notes

- Official IC-Light v1 exposes `gradio_demo.py` for foreground/text
  conditioning and `gradio_demo_bg.py` for background conditioning. The
  background demo loads `iclight_sd15_fbc.safetensors`, patches UNet `conv_in`
  to 12 channels, and concatenates foreground and background VAE latents.
- ComfyUI native workflows make the same distinction: FC workflows use one
  extra latent input; FBC workflows use two. They also warn that transparent or
  masked foreground regions must be grey before VAE encoding.
- Official IC-Light V2/Flux notes currently describe released foreground-only
  variants; foreground+background and HDRI-conditioned variants were listed as
  not released. For the current CG-over-plate CLI, SD1.5 FBC is the public,
  applicable path.

## Latest Probe

2026-06-20 night preflight:

- Added `scripts/check_ic_light_runtime.py` to separate weight-family readiness
  from CUDA availability before launching the expensive runner.
- Current local weights under `weights/ic-light-v2` are SD1.5 IC-Light files
  with compatible UNet `conv_in.weight` channels:
  `iclight_sd15_fbc.safetensors` = 12 channels, `iclight_sd15_fc.safetensors`
  = 8 channels.
- This cron environment could not run a fresh relight: `torch.cuda.is_available`
  was false and `nvidia-smi` could not communicate with the NVIDIA driver.
  Evidence: `reports/ic-light-runtime-check-20260620.json`.

Command shape:

```bash
PYTHONPATH=".deps:." python3 scripts/run_ic_flux.py \
  --plate /path/to/plate_rgb.png \
  --cg /path/to/cg_rgba.png \
  --alpha /path/to/alpha.png \
  --out-dir runs/<case> \
  --prompt "<case prompt>" \
  --width 512 --height 512 \
  --highres-scale 1.5 --highres-denoise 0.5
```

Conservative FBC+transfer results on the three Blender favorites:

- `horse_noon`: Layer 1 pass, edge seam 1.0297, but still worse than raw
  against target (0.29447 vs 0.27172 foreground RMSE).
- `duck_neon`: Layer 1 pass, edge seam 0.8463, better than raw
  (0.21660 vs 0.23835 foreground RMSE).
- `cat_neon`: Layer 1 pass, edge seam 0.6157, better than raw
  (0.14433 vs 0.23906 foreground RMSE).

Artifact summary:

- `runs/ic_light_fbc_transfer_comparison.png`
- `runs/ic_light_fbc_transfer_conservative_summary.json`
