# Latent Delta Workflow

This is the CLI-first path for the original Latent Merge idea from the audio notes:
preserve the object and plate, use a model only to infer bounded lighting/shadow
intent, then apply a controlled delta back onto the original CG.

## Current Status

`latent_delta_proxy` is runnable now. It is not the final model backbone. It is a
workflow scaffold that keeps the trusted output contract stable while making the
proposal/delta/shadow stages inspectable.

The current proposal source is either:

- an external RGB proposal composite passed with `--proposal`, or
- a deterministic local proxy when no proposal is supplied.

The intended next proposal source is FLUX edit/control output, such as FLUX
Kontext/Fill/Depth/Canny, once the right weights or API path are wired.

## CLI

Run the workflow on the default fixture:

```bash
PYTHONPATH=".deps:." python3 cli/run_latent_delta.py
```

Run it with the normal Phase 1 entrypoint:

```bash
PYTHONPATH=".deps:." python3 cli/run_phase1.py --config configs/phase1_latent_delta_proxy.json
```

Run it using an external proposal image from FLUX or another model:

```bash
PYTHONPATH=".deps:." python3 cli/run_latent_delta.py \
  --plate fixtures/golden_synthetic_001/plate_rgb.png \
  --cg fixtures/golden_synthetic_001/cg_rgba.png \
  --alpha fixtures/golden_synthetic_001/alpha.png \
  --proposal runs/my_flux_proposal/proposal.png \
  --output-dir runs/latent_delta_from_flux
```

The proposal image is interpreted as an RGB composite. The workflow recovers the
foreground through alpha and extracts only low-frequency lighting/color deltas.

## Outputs

The trusted output family remains:

- `raw_a_over_b.png`
- `adjusted_fg.png`
- `final_comp.png`
- `alpha_used.png`
- `correction_matte.png`
- `delta.png`
- `alpha_weighted_delta.png`
- `job.json`

Additional Latent Delta inspection outputs:

- `model_proposal.png` — what the proposal source produced.
- `lighting_delta.png` — the bounded foreground lighting/color delta applied to the CG.
- `model_proposal_fg_delta.png` — how far the proposal foreground moved from original CG.
- `shadow_matte.png` — staged receiver shadow/interaction matte.
- `shadow_preview_comp.png` — plate darkening preview for the staged shadow branch.

## Important Contract

`final_comp.png` does not apply the staged cast shadow yet. The current Layer-1
gate checks that the plate is untouched outside the alpha matte. Applying a cast
shadow to the plate before the gate has an explicit interaction mask would look
like a trust-contract failure.

For now:

- foreground lighting/color delta is applied to `adjusted_fg.png` and `final_comp.png`
- shadow artifacts are generated for inspection
- plate shadow application waits for an interaction-mask-aware gate

## GUI

The local UI exposes this as `Latent Delta` in the Model Variant dropdown. It
uses the same pipeline and writes the same artifacts into the UI job output
folder.

The GUI does not yet upload a custom proposal image. Use the CLI for proposal
experiments until the FLUX edit/control proposal backend is wired.
