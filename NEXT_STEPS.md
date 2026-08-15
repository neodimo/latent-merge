# Next Steps — Live Board (verified 2026-08-13 PM)

Read `LOCKED.md` first. `TASKLOG.md` holds the history.

**Status:** Bert paused; Gonzo owns active work and owns every judgement about
imagery. DiMo is escalated to only for hardware, licences, money, public
releases, or reversing a LOCKED constraint.

## Reality check

- Intake is 1/5. `compositingpro_sh009_minimal` is the only accepted case.
  Synthetic and Blender-mediated fixtures are regression sentinels, never
  quality evidence.
- Issue #3 is resolved by Gonzo, not pending: a gnomonic crop of a CC0
  photo-panorama **counts as photographic** under L1 (the plate pixels are
  untouched camera pixels). Its real weakness is capture geometry — a fixed
  nodal point gives no perspective falloff, DOF or motion blur — so such
  plates carry `capture_class: panorama_crop` and the Layer-2 gate
  additionally requires **>= 2 `camera_original` cases**.
- **The matched-panorama toolchain is NOT proven end to end.** It was proven
  on exactly one panorama (2026-06-27, `kloofendal_43d_clear`, alignment MSE
  0.52) and does not generalise: a 2026-08-13 tranche of four new panoramas
  found no azimuth minimum on any of them. Details and evidence:
  `reports/intake-tranche-attempt-20260813/`.
- IC-Light/FLUX relight has still never completed inference. Every visual
  result to date is PCT-Net colour harmonization only.
- GPU: `lspci` shows **no NVIDIA device on the bus** — the eGPU is off USB4,
  not merely driverless. DiMo is reseating it.

## Current cycle — all Gonzo, in order

1. **Projection convention fixed (2026-08-14).** The deterministic mapping is
   Blender azimuth `270 - plate yaw` with camera X rotation `90 - pitch`.
   Four-case pixel evidence is in
   `reports/projection-convention-fix-20260814/`; structural correlation is
   0.831–0.987 and the identity orientation wins on every case.
2. **Tone fixed; ground light transport isolated (2026-08-15).** Plate and CG
   now share Blender AgX. A hidden matte proxy fixes the object's light field,
   but the naive proxy + catcher composite creates a huge polygonal dark veil
   on the plate. Pixel evidence: `reports/ground-proxy-production-20260815/`.
3. **Implement the proxy with an object-on/off difference pass (current).** The
   proxy must exist in both halves; the naive coincident catcher path is rejected.
4. **Replace the CG subject.** An untextured Suzanne leaves LOCKED L4 nothing
   to preserve; use a textured asset on a solved ground plane.
5. **Rebuild the tranche** (`scripts/build_intake_tranche.py`, ~4 min) and
   judge it on pixels, not on validator output.
6. **Then the actual thesis:** one relight backend running end to end on a
   real plate, once CUDA is visible. This is the project. Fixtures are
   scaffolding.

## Standing rules

A validator PASS is plumbing and is never reported as quality. No-op runs
leave no commit, no TASKLOG entry and no post. Look at the image before
believing the JSON.
