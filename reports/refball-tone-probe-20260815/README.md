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

## Next owner + concrete artifact

Gonzo, and this is a change to how fixtures are produced, so it is stated before
it is executed rather than after. Proposal: drop `is_shadow_catcher` for a real
matte ground proxy and extract the shadow as a difference pass — render the
ground with and without the object and use the ratio as the shadow matte. That
occludes and bounces correctly and yields a physically meaningful shadow instead
of a shortcut. It pairs naturally with the proxy wall/occluder geometry already
queued from `reports/ground-contact-20260814/`.

Not started. Awaiting a nod from DiMo since it changes the fixture contract.

## Failure mode recorded

A saturated placeholder material was allowed to stand in for a real asset
through weeks of lighting work. Neutral reference geometry is not a nicety at
the end of a pipeline; it is the instrument that makes lighting errors
measurable, and it belongs in the loop from the first render. The bug was
sitting in plain sight in every composite and no one could see it through the
salmon.
