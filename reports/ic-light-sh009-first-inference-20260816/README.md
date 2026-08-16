# First IC-Light inference on the real sh009 plate

CUDA is finally live and the official SD1.5 IC-Light FBC path completed on the
only accepted photographic case. This closes the hardware/plumbing blocker. It
does **not** pass Layer 2.

## Run

512x288 inference, seed 42, 20 steps, CFG 7, foreground+background conditioning,
then conservative low-frequency transfer back to the original CG. The full
ignored run is `runs/ic_light_sh009_20260816_s42/`.

## Pixel verdict

- `ic_light_model_fg.png`: rejects LOCKED L4. The model replaces the bark-and-
  ember monster with glossy gold/black generated surfaces, loses fine branches
  and texture, and changes the material identity.
- `final_comp.png`: identity survives because the transfer is conservative, but
  the change from `raw_a_over_b.png` is too slight to claim preference. It is a
  mild darkening/cooling, not a persuasive relight.
- Existing flaws remain: hard cutout character, weak ground contact, questionable
  scale/depth integration, and no plate interaction pass in this fixture.

Verdict: **successful real-plate inference, failed quality candidate**. This is
backend evidence only; it contributes zero to the Layer-2 gate.
