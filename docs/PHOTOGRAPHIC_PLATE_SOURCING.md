# Photographic Plate Sourcing — Decision Doc (2026-06-26, current gate unchanged 2026-07-12)

Owner of the open decision: **DiMo**. Author: Gonzo.

## Why this exists

Issue #3 is still waiting on one binary sourcing ruling: whether a rectilinear
crop of a CC0 equirectangular photo-panorama counts as a real photographic plate
under L1. The reason this is the narrow ask: **LOCKED L1 requires the HDRI to be
matched per plate.** Stock CC0 photos do not ship with an on-location HDRI, so a
plate scraped from Unsplash/Pexels can never honestly satisfy L1 — the light
would be guessed. That is exactly the kind of fake progress LOCKED forbids.

## Proposed L1-honest, fully-CC0 path

An equirectangular HDRI panorama (e.g. Poly Haven, CC0) **is itself a real
photograph** stitched to a full sphere. A rectilinear (gnomonic) crop of it is a
genuine photographic plate, and its matched HDRI is — by construction — the
**exact same capture**: same place, same time, same sun. The match is provable,
not asserted.

One panorama yields several distinct plates (different yaw/pitch/FOV), each with
a guaranteed-consistent light rig. So 3–4 Poly Haven panoramas comfortably cover
the 5-case intake tranche and most of the 10–20 locked set.

### Tooling (already built + tested)

- `scripts/pano_to_plate.py` — gnomonic equirect→rectilinear extractor. Emits
  `plate_rgb.png` + `plate_extraction.json` recording the source panorama, its
  CC0 license/URL, the view (yaw/pitch/hfov), and the matched-HDRI hash.
- `tests/test_pano_to_plate.py` — 4 tests, all passing (projection centering,
  horizon placement, yaw shift, manifest/matched-HDRI bookkeeping).
- Visual proof: `reports/pano-plate-method-demo-20260626/method_contact_sheet.png`
  (synthetic pano → 3 rectilinear plates; regenerable, intentionally scratch).

### License confirmation

Poly Haven assets are **CC0** — commercial use, redistribution, and modification
allowed, no attribution required. Source: <https://polyhaven.com/license>.

## The decision DiMo needs to make (yes/no)

**Does a rectilinear crop of a CC0 equirectangular photo-panorama count as a
"real photographic plate" under L1?**

- **YES** → Gonzo selects 3–4 Poly Haven panoramas, extracts 5+ unique plates,
  assembles CG-over-plate + alpha fixtures, lights each CG insert with its own
  source panorama as the matched HDRI, and runs them through
  `validate_photographic_fixtures.py`. This immediately opens the fixture
  intake build; the 5-case gate still has to pass before backend comparison.
- **NO** → the only remaining L1 path is DiMo supplying real use-case footage
  plus its on-set/estimated HDRI. Gonzo stops proposing sourcing and waits.

Either way, this keeps the project on one explicit decision instead of an
open-ended sourcing ask.

## Caveats (stated honestly)

- A pano crop's effective resolution is lower than a dedicated stills camera; for
  1920×1080 plates use ≥8K panoramas (Poly Haven offers up to 24K).
- Panorama LDR previews are tonemapped; relight uses the full-range `.hdr`/`.exr`.
- This still needs CG assets with clean alpha to insert. The sh009 monster and
  CC0 model libraries (Poly Haven models, also CC0) cover that.
