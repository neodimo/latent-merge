# Ground proxy production trial — light field fixed, composite rejected

## Decision

The camera-hidden matte proxy is correct for object lighting but is **not ready
as a production composite** when simply placed under the existing Cycles shadow
catcher. I reject this output on pixels. The next implementation must render the
proxy scene with and without the object and derive interaction from that pair.

## Evidence

`light_field_regression.json` is a 192-sample render against the photographic
`urban_alley_01` panorama. The split path lowers bottom-third sphere luminance
from 0.3020 (no ground) to 0.1957, while catcher-only incorrectly raises it to
0.3566. The production path therefore satisfies the one-sided light-field
invariant. The legacy violation remains an explicit expected known-fail.

`production/composite.png` is the actual plate composite, inspected at
1920x1080 and 256 samples. Its flaws are decisive:

- a huge polygonal dark veil covers the road and climbs the left wall;
- the interaction footprint is many times larger than any plausible ball shadow;
- the chrome ball is partly occluded by the matte ball, weakening the reference pair;
- both balls are oversized for an intake instrument pass;
- the matte ball's top-down gradient and contact are improved, but that does
  not compensate for modifying a vast region of untouched plate.

This is plumbing evidence and a rejection, not Layer-2 quality evidence.

## Code delta

`render_cg_insert.py` now owns `add_light_proxy()` and an asserted visibility
contract. `tests/light_field_regression.py` uses that production helper and
passes only when the split mode satisfies the invariant while the named legacy
catcher failure remains reproducible. The helper is not yet enabled in the
shipping render path because the inspected composite fails.
