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
- **IC-Light FBC completed real-plate inference on 2026-08-16.** The CUDA
  blocker is resolved: the RTX 3080 Ti is visible with 11.6 GiB to PyTorch.
  The first sh009 result is a useful backend proof but not a Layer-2 win: the
  conservative detail-transfer output is almost indistinguishable from raw,
  while the raw model foreground destroys the monster's identity. Evidence:
  `reports/ic-light-sh009-first-inference-20260816/`.

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
3. **Difference pass implemented (2026-08-15).** The object-on/off ratio removes
   the veil and retains local contact; the current acceptance-test strengthening
   in `tests/veil_regression.py` is an unrelated dirty worktree change and was
   left untouched.
4. **Tune or reject IC-Light FBC on sh009.** The backend now runs. The next
   bounded experiment must make a visible lighting improvement while preserving
   the monster; another near-identity conservative transfer is not progress.
5. **Replace the CG subject.** An untextured Suzanne leaves LOCKED L4 nothing
   to preserve; use a textured asset on a solved ground plane.
6. **Rebuild the tranche** (`scripts/build_intake_tranche.py`, ~4 min) and
   judge it on pixels, not on validator output.
7. **Then broaden the actual thesis:** a relight backend that wins over raw on
   real plates. One backend now runs end to end; quality remains unproven.

## Standing rules

A validator PASS is plumbing and is never reported as quality. No-op runs
leave no commit, no TASKLOG entry and no post. Look at the image before
believing the JSON.
