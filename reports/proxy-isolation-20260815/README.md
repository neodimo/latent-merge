# Object-on/off isolation — the veil is the plate merge, not the object

Follows the rejection in `reports/ground-proxy-production-20260815/`. That
report rejected the first production composite because a large veil covered road
and wall, and named the object-on/off difference pass as the next task. This is
that pass.

## What was asked

Bert, 2026-08-15 (#latent-merge): *"Object-on/off with identical proxies in both
halves is the right isolation pass: if the polygon survives, it's proxy/plate
handling; if it cancels, it's object interaction. I'd also keep the proxy
alpha/visibility AOV beside it so we can see whether the veil is literally the
hidden mesh footprint or a downstream mask/math artifact."*

Both are here. The AOV is the `footprint` render and it is what every difference
is measured against.

## Method

`scripts/proxy_isolation_pass.py`. Six renders, one scene construction, camera
and world identical throughout, 1920x1080, 256 spp, seed 0, **denoiser off**,
**linear EXR**. The denoiser is spatial and non-linear so it does not commute
with subtraction, and AgX-encoded PNGs would measure the tone curve rather than
the light; both are why the earlier PNG artifacts could not have answered this.

    bg             world only
    catcher_only   Cycles shadow catcher alone, no object
    proxy_only     camera-hidden matte proxy alone, no object
    proxy_off      both, no object            <- the production ground setup
    proxy_on       both, plus the object
    footprint      the proxy planes forced camera-visible and emissive

Splitting the ground setup in half is the addition to Bert's design. "Proxy or
plate handling" turned out not to be a choice between two components.

## Evidence

Signed luminance difference against `bg`, measured inside the proxy footprint,
excluding the object's own pixels. Figure: `isolation_sheet.png`, all difference
panels on one shared 13.9x gain.

    veil, catcher alone        mean |dL| 0.00003   p99 0.00025
    veil, proxy alone          mean |dL| 0.00000   p99 0.00000
    veil, both (production)    mean |dL| 0.01669   p99 0.07416
    object's interaction       mean |dL| 0.00125   p99 0.03331

Outside the footprint, the production veil is 2e-6 mean and its p99 is exactly
0.0, and the object's interaction is exactly 0.0. So the veil is bounded by the
hidden mesh's footprint to the pixel, and nothing downstream is smearing it.

## What this attributes

**The proxy's visibility contract holds.** `proxy_only` differs from `bg` by
exactly zero at 256 spp — not "small", zero. Camera-invisible geometry is not
reaching the camera path, so the image-space leak hypothesis is wrong.

**The shadow catcher alone is clean.** With nothing to occlude it, it passes the
plate through.

**The defect is their interaction.** The catcher computes its plate merge as a
shadowing ratio against every object that occludes it, and the coincident proxy
is such an object. The proxy's occlusion of the catcher's own world sampling is
therefore written into the plate as if it were a cast shadow — across the entire
200 m plane, which is 35% of frame. That is the polygon.

**The veil is 13.4x the object's entire contribution.** The rejection was
correct and was aimed at the right layer.

## The fix, measured rather than proposed

A veil identical in both halves cancels out of the ratio `proxy_on / proxy_off`,
which is what a difference-based composite multiplies the plate by. Over the
600,816 footprint pixels the object provably does not touch:

    additive veil                   0.017448
    ratio deviation from 1.0        0.000161 mean, 0.001558 p99
    suppression                     108.6x

So the difference composite named in the rejection removes this specific defect
by construction, and the isolation data confirms it on this frame. It does not
follow that the resulting composite is correct — that needs its own inspection,
and the object was still oversized and poorly placed in the rejected frame.

## Standing rule

Bert's wording, kept verbatim because it is the transferable part:

> Do not diagnose catcher/proxy defects from a single composite. Render
> component halves and the hidden-proxy footprint AOV; interaction defects can
> emerge only from the paired operator.

## Acceptance test

`tests/veil_regression.py` turns this from a one-off measurement into a scoped
gate, per Bert's framing: identical ground field in both halves, residual
measured on footprint only, outside a geometric exclusion zone around the
object, against an absolute budget.

    metric              |ratio - 1|, the setup's multiplier on untouched plate
    budget              2e-3 mean, 2e-2 p99
    production          1.4e-04 mean, 2.9e-03 p99   -> passes, 14.1x headroom
    legacy catcher+proxy  1.9e-01 mean, 3.1e-01 p99 -> exceeds budget by ~94x

The legacy arm is required to keep failing. If the rejected setup ever stops
exceeding the budget, the test exits 1 on the grounds that it has stopped
demonstrating it can detect the defect. Both failure paths and the pass path
have been exercised and return the expected exit codes.

It asserts only that untouched plate stays untouched. It does not claim the
composite is approved.

## Caveats

- One frame, one HDRI, one placement. The cancellation number is a property of
  this data, not a proof about the pipeline.
- The ratio is undefined where `proxy_off` is black; the 1e-6 epsilon used here
  is adequate for this plate and is not a general solution.
- Nothing in the shipping render path changed. `render_cg_insert.py` gained
  linear/denoise/seed controls on `render()` and nothing else.
