# One tone curve end to end: plate and render now leave through the same transform

DiMo, 2026-08-15 (#latent-merge): *"Good solve, but make sure the images are
tonemapped correctly."*

This was already defect (2) on my own list from 2026-08-13 ("my Reinhard tonemap
yields washed-out non-photographic plates") and the queued next action from
2026-08-14. It was worse than "washed out".

## The actual defect

Two different tone operators were being applied to the same captured radiance:

- **plate**: HDR equirect -> OpenCV `createTonemapReinhard(gamma=2.2,
  intensity=0.0, light_adapt=0.9, color_adapt=0.0)`
- **CG render**: Cycles -> Blender's default **AgX** view transform, which
  `render_cg_insert.py` never set and therefore inherited silently

A tone mismatch baked in at the source cannot be closed by any relight stage
downstream, because the plate and the insert are not in the same display space.
It also silently corrupted our own instrumentation: the projection scores had to
normalise contrast away to say anything about geometry at all, which is why the
geometry work has been reading tone-blind scores for weeks.

## The fix

`scripts/tonemap_pano.py` (new) tonemaps the panorama through **Blender's own
OCIO view transform** via `Image.save_render`, i.e. the identical operator Cycles
writes a render through. The HDR is read as `Linear Rec.709` so the transform is
not applied on top of already-encoded pixels.

`scripts/render_cg_insert.py` now **pins** colour management (`--view-transform`,
`--look`, `--exposure`, `--gamma`, default AgX) and re-applies it inside
`render()` before every write, because each scene reset restores factory
settings. An unavailable transform name is a hard error in both scripts rather
than a silent fallback.

`scripts/build_intake_tranche.py` calls the Blender tonemapper, and the fixture
field is now `blender-ocio(AgX,look=None,exposure=0.0,gamma=1.0)` instead of the
Reinhard string. Both plate and render take the transform from one constant.

## Evidence

Case: Poly Haven `urban_alley_01`, yaw 0 / pitch -6 / hfov 72, 1920x1080, 256
samples. Plate vs the Blender background render at the same camera, measured in
linear on raw (**not** contrast-normalised) pixels:

| metric | OLD Reinhard | NEW AgX |
| --- | --- | --- |
| raw MSE | 0.007669 | **0.000050** (153x better) |
| mean delta | +0.02390 | **-0.00103** |
| std ratio (plate/render) | **0.562** | **0.993** |
| normalised identity correlation | 0.9855 | **0.9995** |

The std ratio is the washout stated numerically: the Reinhard plate carried 56%
of the contrast the render assumed. Plate histogram also went from p1..p99 of
43..193 to 14..233, mean 95.7 -> 74.5, with no highlight clipping either way.

The normalised geometry correlation improving 0.9855 -> 0.9995 is a side effect
worth noting: tone disagreement was polluting even the tone-normalised score.

`plate_tonemap_ab.png` is the full-frame before/after — the Reinhard plate is a
grey wash, the AgX plate has real blacks in the shopfronts and a sky that reads
as sky. `tonemap_sheet.png` carries plate A/B, the ground grid, and the
composite. Ground contact from 2026-08-14 is unchanged and re-verified:
`bbox_min_z` 0.0, 72 stray alpha pixels pruned, 63 869 kept.

## What this does not fix

- **The CG object never changed.** It was always rendering through AgX; the
  plate was the wrong one. So the visual step-change is in the plate, and at
  object scale (`composite_ab.png`) the difference is modest. The object still
  does not belong to the scene tonally or chromatically — flat and pink against
  an overcast alley. That is the relight stage.
- **This matches a tonemapped panorama to a render, not a camera to a render.**
  A real `camera_original` plate carries its own camera tone curve, and the
  render must then be matched to *that*, not to AgX. Layer-2 requires >= 2
  camera_original cases, so this fix does not carry over to them for free.
- The flat-plane world, missing curb, and untextured Suzanne from
  `reports/ground-contact-20260814/` are all still open.

## Next owner + artifact

Gonzo. Rebuild the four-case tranche through the corrected chain
(`scripts/build_intake_tranche.py`, which now wires both ends to
`VIEW_TRANSFORM`), then proxy occluder geometry, then a textured asset.

## Failure mode recorded

The render script never set colour management and inherited a default, while the
plate path set an explicit and different one. An inherited default on one side of
a comparison is an unstated assumption; both sides of a pixel comparison must
name their transform, and the metric must include an un-normalised term so a tone
mismatch cannot hide behind contrast normalisation.
