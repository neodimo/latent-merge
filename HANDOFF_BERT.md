# Bert Handoff

Updated: 2026-07-07

## Current Status

This is a historical handoff, not the active project contract. Bert is paused on
latent-merge until Omid re-engages him. Current workers should use
`LOCKED.md`, `WORKFLOW.md`, `NEXT_STEPS.md`, `AUTOMATION.md`, and
`PHASE2_GATE.md` for ownership, gates, and reporting.

Do not treat the May runtime notes below as current. Later checks showed this
cron environment cannot see NVIDIA hardware or CUDA, and the quality gate is
blocked on DiMo's issue #3 ruling about CC0 panorama-derived photographic
plates.

## Source

This file captures Gonzo's Discord handoff for Bert. Gonzo also reported a host-local handoff file at:

```text
/var/home/omid/.openclaw/workspace/projects/latent-merge/HANDOFF_BERT.md
```

That path is on Gonzo's machine, not Bert's VPS, so the channel handoff is copied here as repo context.

## Current Direction

- PCT-Net / AICT is the conservative harmonization baseline, not final proof.
- IC-Light V2 / FLUX relight remains a comparison lane, but no real relight
  output has been produced yet.
- The active blocker is the locked photographic intake set: issue #3 needs
  DiMo's YES/NO ruling on whether a rectilinear crop of a CC0 equirectangular
  photo-panorama counts as a real photographic plate under L1.
- Keep the trust contract:
  - adjusted foreground
  - debug passes
  - final comp over untouched plate
  - no opaque AI-painted final comp as the main result

## Historical Gonzo Runtime State

These notes are preserved only to explain old decisions:

- Gonzo previously reported RTX 3080 Ti access on `card0` / `cuda:0`.
- Gonzo previously reported CUDA runtime working in `latent-merge/.venv`.
- Gonzo was in low-credit mode until May 30, 2026 at night.
- Bert was expected to handle repo/docs/pipeline wiring and hand Gonzo only
  small GPU execution packets when needed.

Current project docs supersede all four points.

## Fixture

Use the Compositing Pro free Nuke CG compositing tutorial files as the first practical fixture.

License caveat: the source page says the files are for personal practice only and not commercial use.

Phase 1 fixture should be simplified to:

- `plate_rgb.png`
- `cg_rgba.png`
- `alpha.png`

Ignore extra passes for now, including albedo, diffuse, specular, light groups, shadows, and other AOVs.

Gonzo reported the minimal fixture staged locally as:

```text
fixtures/compositingpro_sh009_minimal/plate_rgb.png
fixtures/compositingpro_sh009_minimal/cg_rgba.png
fixtures/compositingpro_sh009_minimal/alpha.png
```

Historical caution: Gonzo said these PCT-Net/fixture files were uncommitted on
his side in May. Check `git status` before touching generated fixtures or runs.

## PCT-Net Spike Result

Gonzo reported PCT-Net runs here:

```text
runs/pctnet_compositingpro_sh009/cnn/
runs/pctnet_compositingpro_sh009/vit/
runs/pctnet_compositingpro_sh009/contact_sheet.jpg
```

Reported read:

- CNN looks safer and more conservative.
- ViT is stronger but has more identity risk.

The useful next move is to make PCT-Net a stable Phase 1 backend behind the existing CLI/output contract.

## IC-Light V2 / FLUX Comparison Lane

If piping this option, use the same inputs:

- plate RGB
- CG RGBA
- alpha

Constraints:

- proxy resolution first
- return adjusted foreground and debug outputs, not only a painted composite
- check licensing, access, and localization before relying on it
- compare against PCT-Net on identity preservation, alpha edges, repeatability, and integration quality
