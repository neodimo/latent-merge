# Next Steps

## Immediate Spike

Run a two-week offline model bakeoff before building too much Nuke code.

Needed from DiMo/team:

- 20-30 representative CG-over-plate test cases if available
- CG RGBA
- plate
- alpha/matte
- desired artist comp/reference if available
- optional depth/normal/AOVs
- at least a few short sequences, even if proxy/cropped, to expose flicker early

## Candidate First Tests

- IC-Light / IC-Light V2 / FLUX relighting graph via ComfyUI cloud
- DiffHarmony++ / harmonization baseline
- PCT-Net or AICT-style color-transform baseline
- ControlCom if accessible
- DreamLight/CFDiffusion if accessible and practical

## Bert Phase 1 Lane

- Keep `cli/run_phase1.py` stable as the reproducible entrypoint.
- Add the first real backend behind `core/pipeline.py` without changing output filenames.
- Preserve `job.json` input hashes, backend metadata, and diagnostics for every run.
- Treat Nuke as a later thin caller of the CLI/service until the backend produces useful results.

## Success Criteria

- CG asset identity preserved.
- Lighting/color integration visibly improved.
- Plate remains untouched and inspectable.
- Alpha edges do not become worse.
- Short sequence does not flicker catastrophically at proxy settings.

## First Nuke Prototype Shape

- Nuke gizmo/Python node accepts A/B/alpha and optional AOVs.
- Nuke sends cropped/proxy frames to a local inference service.
- Service returns adjusted foreground and diagnostics.
- Nuke performs the trusted A-over-B composite over original plate.
- Debug outputs are exposed as inspectable passes.
