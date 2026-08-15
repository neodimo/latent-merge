# Neutral reference asset — and the lighting bug it exposed

Bert, 2026-08-15 (#latent-merge), on the tonemap sheet: *"the Suzanne still has
that saturated salmon CG material, which can hide whether the lighting ratio is
right. I'd add a neutral gray/matte asset pass next to separate tone-path
correctness from material ugliness."*

Correct call. The pass took twenty minutes and found a physical error in the
lighting that the coloured placeholder had been covering for weeks.

## What was added

`scripts/render_cg_insert.py` gains `--asset {suzanne,gray_ball,ref_balls}`.
`ref_balls` is the on-set pair: an 18% matte sphere whose shading gradient is
readable against the plate's own midtones, and a chrome sphere whose reflection
of the environment can be compared directly with the surrounding plate pixels.
Neutral by construction, so anything ugly left in the frame is the light or the
tone path rather than the material.

## What the chrome ball says: the tone path is good

The chrome sphere reflects the alley's warm sunlit upper facade and the bright
sky slot, and that reflection reads at the same tonality as the plate around it.
That is a genuine end-to-end confirmation of yesterday's fix — HDRI, render, and
plate are in one display space.

## What the gray ball says: the ball is lit from below, through the ground

The 18% sphere sits at 2.34x the luminance of the road it rests on, which is
defensible for 18% over ~8% asphalt. The *gradient* is not: p90/p10 across the
visible sphere is only 2.46, far flatter than a narrow overhead sky slot between
two dark walls should produce. So I measured the same ball three ways.

Gray ball luminance, linear, 192 samples, identical placement
(`diag_ground_occlusion.py`, `ground_occlusion.json`):

| ground | mean | top | bottom | top/bottom |
| --- | --- | --- | --- | --- |
| `is_shadow_catcher` (what we ship) | 0.3986 | 0.4294 | 0.3547 | **1.211** |
| real 8% matte plane | 0.2660 | 0.2658 | 0.2653 | 1.002 |
| no ground at all | 0.3702 | 0.4278 | 0.2993 | 1.429 |

Read the first and third rows together. Adding the shadow-catcher ground made
the sphere's **underside brighter** (0.2993 -> 0.3547) and the whole sphere
brighter (0.3702 -> 0.3986). A ground plane must only ever *remove* light from
an object's lower hemisphere.

The cause: a Cycles shadow catcher is not a real occluder for another object's
indirect rays. The environment texture's lower hemisphere — which for this
panorama is sunlit alley road — shines straight through the plane and onto the
sphere's underside. Swapping in real matte geometry occludes it properly and the
object drops **33% in mean luminance** (0.3986 -> 0.2660).

Every CG insert this pipeline has produced is therefore over-lit from below by
light passing through the ground it is standing on. The salmon Suzanne could not
show this: a saturated material flattens the readable shading range, which is
precisely Bert's point.

## On Bert's first tell (deep blacks vs camera plates)

Already recorded in `reports/tonemap-match-20260815/` — AgX is matched to a
tonemapped panorama, not to a camera's curve, and Layer-2's >= 2
`camera_original` cases will need the render matched to *their* curve instead.
Worth adding: the ref-ball pass is the instrument for that too. A neutral sphere
makes a curve mismatch legible where a coloured material hides it, so the ball
pass should be the first thing rendered against any new camera plate.

## The regression fixture, and Bert's fix measured

Bert then asked for the ball comparison to be kept as a regression fixture, and
proposed a better fix than my difference-pass idea: keep the shadow catcher for
the plate merge, and add proxy geometry that is **visible to diffuse/glossy rays
and hidden from camera** to do the blocking and bouncing.

`tests/light_field_regression.py` is that fixture. It renders an 18% matte sphere
over four ground modes at identical placement and asserts one invariant:

> `bottom_luminance(with_ground) <= bottom_luminance(no_ground)`

A ground plane occludes part of the environment and bounces back a fraction of
what it receives; for any ground darker than the environment below the horizon,
the net must be a decrease. Exit 0 = holds everywhere, exit 1 = violated.

Gray ball luminance, linear, 192 samples, `urban_alley_01`
(`light_field_regression.json`, `three_ball_regression.png`):

| ground mode | mean | top | bottom | top/bottom | invariant |
| --- | --- | --- | --- | --- | --- |
| no ground (baseline) | 0.3702 | 0.4278 | 0.2993 | 1.429 | — |
| `is_shadow_catcher` (shipping) | 0.3986 | 0.4294 | 0.3547 | 1.211 | **VIOLATED** by 0.0554 |
| real matte ground | 0.2660 | 0.2658 | 0.2653 | 1.002 | holds, but hides the plate |
| **catcher + hidden light proxy** | 0.3053 | 0.4022 | **0.1906** | **2.110** | **holds** |

Bert's split setup is the only configuration that passes the invariant while
leaving the plate visible, and it produces the strongest directional gradient of
the four (2.11), which is what a narrow overhead sky slot between dark walls
should give. The fully visible matte ground passes the invariant only by
flattening the sphere to 1.00 and covering the photograph.

**What this does not establish:** the invariant is one-sided. It proves the
underside stopped being lit through the floor; it does not prove 0.1906 is the
*correct* value. That needs a ground-truth reference, not a regression bound.

## Next owner + concrete artifact

Gonzo. The fix is now measured rather than assumed, but applying it changes how
fixtures are produced, so it is still stated before it is executed. Proposed:
adopt the split setup in `render_cg_insert.py` — catcher for the merge, a
camera-hidden matte proxy for the light field — and extend the same treatment to
the wall/car occluder proxies queued from `reports/ground-contact-20260814/`,
which must block and bounce in the CG world while staying invisible in the final
plate.

Not started. Awaiting a nod from DiMo since it changes the fixture contract.
Logged as an open known-fail in `PHASE2_KNOWN_FAILS.md`; the test is committed
failing on purpose, and it is the gate that will confirm the fix.

### Luminance strips: the defect without the full-frame read

Bert asked for the balls cropped with nearby asphalt plus luminance strips down
the gray sphere, so the over-lit underside is legible without reading the whole
frame. `scripts/plot_ball_luminance.py` does that: mean luminance per scanline
inside the sphere's own mask, crown to contact point, all ground modes on one
axis, with the plate's nearby asphalt as a reference line.

`ball_luminance_strips.png`. Contact = mean of the last 8 scanlines;
asphalt = 0.0628.

| mode | crown | contact | contact / asphalt |
| --- | --- | --- | --- |
| no ground | 0.1574 | 0.0431 | 0.69 |
| `is_shadow_catcher` | 0.1561 | **0.0464** | 0.74 |
| catcher + hidden proxy | 0.1513 | **0.0059** | 0.09 |

The shaded wedge is the light the shadow-catcher ground *added* to the sphere.
It is zero at the crown — 0.1561 vs 0.1574, correct, a floor should not change
the top of an object — then opens through the entire lower two-thirds before
pinching shut at the tangent point where geometric occlusion dominates
regardless. That wedge is the bug, drawn.

The proposed split setup falls away steeply instead, which is the shape a
sphere resting on an opaque road should have.

Same caveat as the invariant: 0.0059 being 11x darker than the asphalt is
plausible at a tangent point, but this figure shows the *shape* is now right, not
that the level is calibrated. Ground truth is still owed.

### The decision, specified

Bert and I converged on this contract (2026-08-15). Writing it out so DiMo is
approving something precise rather than a direction:

1. **Real matte/proxy geometry participates in light transport.** Ground, and
   later walls and the parked car, are camera-invisible and ray-visible. They
   block and bounce in the CG world while staying absent from the final plate.
2. **The shadow/contact contribution comes from a difference pass** — the proxy
   set rendered with and without the object — instead of asking a shadow catcher
   to be simultaneously a compositing trick and a physical receiver.
3. **The proxies are included in both halves of that pair** wherever they affect
   occlusion or bounce, or the difference is not a shadow, it is an artefact of
   inconsistent scenes.

Bert's two guardrails on the call:

- **Keep the shadow-catcher path measurable as a baseline until the diff-pass
  numbers are stable.** Already structural rather than a policy:
  `tests/light_field_regression.py` renders every ground mode on every run, so
  the legacy path stays in the table by construction. Noted in `WORKFLOW.md`
  that removing a mode to make the test green is not allowed.
- **`ref_balls` is the first render against every new plate**, especially the two
  Layer-2 `camera_original` cases, because it reads tone curve, indirect
  occlusion, and HDRI/world alignment before any asset can confuse it. Actuated
  as intake law in `WORKFLOW.md`, not left as a chat agreement.

## Failure mode recorded

A saturated placeholder material was allowed to stand in for a real asset
through weeks of lighting work. Neutral reference geometry is not a nicety at
the end of a pipeline; it is the instrument that makes lighting errors
measurable, and it belongs in the loop from the first render. The bug was
sitting in plain sight in every composite and no one could see it through the
salmon.
