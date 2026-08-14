# Projection convention fix — 2026-08-14

The mismatch was two deterministic basis errors in `render_cg_insert.py`:

- panorama yaw maps to Blender azimuth as `270 - yaw`, rather than the same
  numeric angle;
- `pano_to_plate.py` negative pitch looks up, so Blender camera X rotation is
  `90 - pitch`, rather than `90 + pitch`.

`plate_vs_blender_fixed.jpg` shows the four real photographic crops on the
left and Blender background checks on the right. I inspected the pixels. Scene
geometry, framing, horizon and orientation now reproduce on all four cases.
The strongest structural correlations are 0.955 (harsh sun), 0.987 (indoor)
and 0.986 (urban alley). Venice is lower at 0.831 because the current Reinhard
plate tonemap is badly washed out relative to Blender's view transform; its
buildings, tree, fence and road still register at the same pixels.

Remaining flaws, excluded from this fix's verdict:

- plate and Blender tone curves do not match; Venice is the clearest failure;
- the plates remain washed out and the indoor plate has a visible panorama
  seam/discontinuity;
- Suzanne remains untextured, floats, and provides no meaningful L4 identity
  test.

The old azimuth optimiser was removed from the execution path. It had selected
wrong views when tone differences dominated its grayscale score. The renderer
now uses the known transform and records identity plus mirror scores in
`render_meta.json`. `scores.json` preserves the four-case diagnostic values.

This is projection evidence only. It does not make any fixture quality-bearing
and does not change intake from 1/5.
