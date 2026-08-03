# Next Steps — Live Board (verified 2026-08-03 PM)

Read `LOCKED.md` first. `TASKLOG.md` holds the pulse-by-pulse history.

**Status:** Bert is paused; Gonzo owns active project work.

## Reality check

- The intake has one accepted photographic case: `compositingpro_sh009_minimal`.
  Synthetic and Blender-mediated fixtures are regression sentinels, not quality
  evidence.
- IC-Light/FLUX relight has never completed inference. Existing visual results
  are PCT-Net color harmonization only. This worker runtime cannot see NVIDIA
  hardware; use `HARDWARE.md` before scheduling GPU work.
- The matched-panorama toolchain is complete and proven end to end:
  `pano_to_plate.py` -> `render_cg_insert.py` -> `assemble_fixture.py` ->
  `validate_photographic_fixtures.py`. Reproduction evidence is in
  `reports/cg-insert-matched-hdri-20260627/`.

## Current cycle

1. **DiMo:** answer GitHub issue #3: does a rectilinear crop of a CC0
   equirectangular photo-panorama count as a real photographic plate under L1?
2. **Gonzo, after YES:** produce and validate the 5-case photographic intake
   tranche with the proven matched-HDRI chain.
3. **DiMo, after NO:** supply real footage/plates plus matched HDRI; Gonzo then
   assembles and validates the intake tranche.
4. **Gonzo, after intake:** run Layer 1 and produce raw A-over-B vs PCT-Net vs
   relight comparison evidence. A real relight backend also requires a runtime
   with visible CUDA hardware.
5. **Review lane:** run blind Layer-2 preference scoring only after accepted
   photographic cases clear Layer 1. Release packaging remains gated by issue
   #6.

## Current evidence and worker rule

Issue #3's body was narrowed on 2026-08-01 to explicit YES/NO decision
checkboxes; no ruling has been made. Its title now names that decision directly,
its labels identify it as a blocked Phase 2 fixture task, and GitHub formally
assigns it to DiMo. Downstream release issue #6 is now explicitly labeled
`blocked` until accepted photographic Layer-2 evidence exists. No PR is active.
Do not rerun unchanged intake or CUDA checks.
Act on a checked ruling, new input, newly visible CUDA hardware, or newly
verified project drift; otherwise stay silent.

## Today's concrete gate

DiMo owns the YES/NO ruling in issue #3. The most valuable review today is that
single decision. YES starts the 5-case intake build; NO switches sourcing to
DiMo-provided plates/footage and matched HDRI.
