# Difference composite — the veil is gone and the contact survives

Implements the fix that `reports/proxy-isolation-20260815/` attributed and
measured. `scripts/composite_difference.py`.

## Method

No shadow catcher anywhere in this path. The ground is an ordinary camera-visible
matte surface rendered twice, and the object's effect on it is the ratio:

    ratio      = ground_with_object / ground_alone
    composite  = plate_linear * ratio * (1 - object_alpha) + object_rgb

Anything the ground does on its own is identical in both halves and divides out,
which is why the veil cannot come back through this construction. The object is
rendered separately over transparent film with the ground switched to the
camera-hidden ray-visible proxy, so it is lit by the same surface it stands on
without that surface entering its alpha.

Three renders, one scene construction, 1920x1080, 512 spp, seed 0, denoiser off,
linear EXR. A ratio between two denoised images is not a ratio between two
renders.

## Evidence

`difference_sheet.jpg` — rejected composite and this one side by side, plus a
plate/composite zoom on the contact.

    plate modified                     0.45% of frame  (was 35%)
    off-object plate delta, mean       7.4e-05
    ratio mean off object              0.9995
    interaction near object (<250px)   5.5% of pixels touched, min ratio 0.039
    interaction far from object (>600px)  109 pixels in the entire frame

The contact shadow is present and tight under both spheres — a real minimum
ratio of 0.039 — while the rest of the plate is left alone. That is the shape
the rejection asked for: a local interaction instead of a repainted road.

## Also fixed here

`orient_across_view()` in `render_cg_insert.py`. The reference pair offsets the
chrome sphere along local +X, and whether that axis ran across frame or straight
away from camera was pure luck of the plate azimuth. In both 2026-08-15
composites it ran away from camera and the matte sphere occluded most of the
chrome one, so the pair was not a usable instrument. It is now rotated
perpendicular to the ground-projected view direction (93.245 deg here) before
seating, and both spheres read.

## Honest remaining flaws

Stated because the composite is not finished, only unblocked:

- **The spheres are razor sharp against a visibly defocused plate region.** No
  lens blur or grain match. This is the largest remaining tell by eye and it is
  a downstream problem this pass does not touch.
- The matte sphere reads slightly warm from wall bounce. Plausible, unverified
  against any ground truth.
- The plate is decoded with the sRGB EOTF, but it is an already-tonemapped LDR
  image, so the linear values the ratio multiplies are an approximation. A true
  scene-linear plate cannot be recovered from it.
- One frame, one HDRI, one placement, one asset.
- **Nothing is wired into the shipping render path.** `render_cg_insert.py`
  still ships the catcher-only setup and `tests/light_field_regression.py` still
  measures the catcher-based modes. Known-fail 9 is unchanged.
