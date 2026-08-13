# Intake tranche attempt — 4/4 validator PASS, 0/4 actually usable (2026-08-13)

Built fixtures #2–#5 on the "proven" matched-HDRI chain to clear the 12-day
issue-#3 stall. The validator passed all four. **The fixtures are not
acceptable and were not committed to `fixtures/`.** This report exists because
the failure is more valuable than the tranche would have been.

## What was run

```
build_intake_tranche.py  (new)
  → tonemap_hdr (NEW — this step was never scripted; the 2026-06-27 chain did
    it by hand, which is why pano_to_plate.py accepts an LDR image it cannot
    produce)
  → pano_to_plate.py → render_cg_insert.py (Blender CPU) → assemble_fixture.py
  → validate_photographic_fixtures.py  →  ok: true, 4/4, 1920x1080
```

Four lighting regimes deliberately chosen to break harmonization differently:
harsh direct sun (`syferfontein_18d_clear`), low warm sun with heavy colour
cast (`venice_sunset`), indoor soft ambient (`st_fagans_interior`), overcast
urban shade (`urban_alley_01`). All CC0 Poly Haven.

Total compute: about four minutes. This is worth stating plainly — the work
that was gated behind a checkbox for twelve days takes four minutes to run.

## Defect 1 — matched-HDRI alignment does not reproduce (blocking)

`render_cg_insert.py` finds the world azimuth whose Blender background best
reproduces the plate. On 2026-06-27 that found a real minimum on
`kloofendal_43d_clear`: **MSE 0.52 vs ~1.0 off-axis**. On all four new
panoramas it finds nothing:

| case | plate yaw | found azimuth | MSE |
|---|---|---|---|
| syferfontein_harsh_sun | 30 | 45 | 0.788 |
| venice_low_sun | 200 | 70 | 1.279 |
| stfagans_indoor_soft | 90 | 55 | 1.227 |
| urban_alley_overcast | 0 | 125 | 1.104 |

A full 5° sweep of all 360° on the venice case (`az_error_surface_venice.json`)
shows the error surface has **no true minimum anywhere**: best 1.287, worst
2.636. Descriptors are zero-mean/unit-variance, so MSE = 2(1−corr); the best
azimuth in the entire sweep correlates with the plate at **r = 0.36**. A
correct alignment lands near r = 0.74. Raising search resolution (160×90 →
320×180) and swapping to a gradient/edge descriptor both failed to produce a
minimum, so this is not a search-tuning problem — the Blender background cannot
reproduce the plate at any azimuth. That points at a projection-convention
mismatch between `pano_to_plate.py`'s gnomonic crop and Blender's equirect
environment lookup (candidate causes: vertical flip, pitch sign, or hfov
interpretation), not at the optimiser.

Consequence: the "matched" in matched-HDRI is currently **asserted, not
proven**, on every case except the single June one. `NEXT_STEPS.md` describes
this chain as "complete and proven end to end"; it was proven on exactly one
panorama and does not generalise.

## Defect 2 — the tonemap produces non-photographic plates (mine)

`tonemap_hdr`'s Reinhard settings (`light_adapt=0.9`) crush contrast and
desaturate. See panels 1 and 3 of the contact sheet: the syferfontein and
st_fagans plates read as faded scans, not photographs, and the st_fagans plate
carries a visible horizontal discontinuity across the frame. A plate that does
not look photographic is worthless as a Layer-2 bed regardless of what
`plate_provenance` says. Needs a filmic/AgX-style curve matched to Blender's
view transform — which would also remove tone as a confound from Defect 1.

## Defect 3 — the CG subject is not quality-bearing

`render_cg_insert.py` inserts an untextured Suzanne. In the composites it
floats with no believable ground contact (rows 1, 3, 4), and in row 1 its
contact shadow reads as a black sticker. Flat salmon clay with no texture,
logos or fine detail means **LOCKED L4 has nothing to preserve** and Layer-2
preference scoring would be measuring almost nothing. Needs a textured asset
placed on a solved ground plane.

## Verdict

Not committed as fixtures. Intake remains 1/5 (`compositingpro_sh009_minimal`).
The relight backend was never the thing blocked by the checkbox — the fixture
chain has three defects that only running it could expose.

## Next actions, in order

1. Fix the projection convention (Defect 1). Diagnostic: render the Blender
   background at the plate's exact yaw and diff against the plate, and against
   its horizontal and vertical mirrors. Whichever mirror correlates identifies
   the flip.
2. Replace the tonemap with a Blender-matched view transform (Defect 2).
3. Swap Suzanne for a textured asset on a solved ground plane (Defect 3).
4. Only then rebuild the tranche.

GPU is unrelated to all three — `nvidia-smi` reports no driver and `lspci`
shows no NVIDIA device at all (eGPU off the bus). That blocks the relight
backend, not this work.
