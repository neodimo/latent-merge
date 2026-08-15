# Sharpness and grain mismatch, measured

`scripts/measure_sharpness_grain.py`. Turns the eye judgement at the end of
`reports/difference-composite-20260815/` — "the spheres are razor sharp against
a defocused plate, with no grain" — into two numbers with corrections attached,
per Bert's framing that rebasing known-fail 9 should mean *better final
composite*, not just *veil cancelled*.

## Results

    acutance   CG insert   0.98 px   plate  1.60 px   ratio 1.62x
               -> apply gaussian sigma 1.26 px to match the plate's defocus

    grain      CG insert   0.00097   plate  0.00259   ratio 2.67x
               -> add grain of sigma 0.0024 to match the plate's noise floor

Both mismatches are real and both now have a number a later matching pass can be
gated against.

## One of the two eye judgements was wrong

The composite report claimed the insert had "no grain". It had *too much*: the
first measurement put the CG at 0.00523 against the plate's 0.00259, so the
insert was **2x noisier than the photograph it sits in**.

The cause was mine. `composite_difference.py` rendered every pass with the
denoiser off. That is required for `ground_only` and `ground_object`, because the
denoiser is spatial and does not commute with division, so it would invent
structure in the ratio. But `object_only` is composited directly and appears in
no ratio, so switching it off there only injected raw path-trace noise into the
final image for nothing. Fixed; the insert's grain dropped 5.4x to 0.00097 and
the mismatch flipped to the expected direction.

Worth keeping: "it looks noise-free" and "it has less noise than the plate" are
different claims, and the sign of the error was not visible by eye at all.

## The instrument had to be fixed twice before it could be trusted

Run `--self-test` before quoting anything from this script. It blurs the plate by
known sigmas and checks the measurement recovers them; `self_test.json` here is
the passing run.

1. **10-90% rise distance** — rejected. Needs a clean step, and a sphere's limb
   shading keeps changing for tens of pixels past its silhouette, so any window
   wide enough for the transition also holds the shading. It reported an 11 px
   edge on a silhouette antialiased over about one pixel.
2. **Second moment of the line spread function** — the textbook route, and it
   *failed the self-test*: given a known 0.8 px blur it recovered 0.53 px. With a
   dozen samples, noise in the far tails is weighted by distance squared and
   drags the width toward the window size. It made plate and CG both measure
   ~2.4 px regardless of what they were, which looks like "no mismatch" and is
   entirely an artifact of the estimator.
3. **Error-function fit** — passes, recovering 0.8/1.5/2.5 px as 0.64/1.34/2.10.

That third row is a systematic under-read of roughly 15-20%, so the *ratio*
between plate and CG is trustworthy and the absolute widths are conservative.
The implied correction is therefore a lower bound.

Had the self-test not been written, version 2 would have reported "plate 2.40 px,
CG 2.41 px, no mismatch" and closed a real defect as measured-and-fine.

## Caveats

- One frame, one HDRI, one placement, one asset.
- Grain is measured as a single scalar std. Real sensor grain has colour
  correlation and a spatial frequency signature this does not capture, so
  matching this number is necessary and not sufficient.
- The plate's edge width is measured on its sharpest available edges within a
  band around the object's depth. A plate with genuine depth of field varies
  across the frame and one number cannot describe it.
- Nothing is corrected. This measures only.
