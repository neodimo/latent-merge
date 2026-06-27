# Matched-HDRI CG insert — last L1 link proven end-to-end (2026-06-27 afternoon)

Closes the last technical unknown in the LOCKED L1 fixture chain. As of this
morning (commit 49c13dd) `assemble_fixture.py` only had a *procedural placeholder*
pass the validator. This run produced a **real, HDRI-lit, quality-bearing CG
insert** and ran the full chain to a validator PASS:

```
pano_to_plate.py  →  plate_rgb.png + plate_extraction.json
render_cg_insert.py (Blender, NEW) → cg_rgba.png lit by the matched HDRI + contact shadow
assemble_fixture.py --cg → fixture.json with cg_insert_is_quality_bearing: true
validate_photographic_fixtures.py → ok: true  (dims 1920x1080)
```

`cg_insert_contact_sheet.png` panels:
1. the real photographic plate (B), CC0 Poly Haven `kloofendal_43d_clear`, gnomonic crop yaw 0 / pitch -5 / hfov 75
2. the Blender world (HDRI) render at the auto-found azimuth (265°) — matches panel 1 (plate↔bg normalized corr 0.729), so camera/world alignment is verified, not asserted
3. the CG object lit by the **same** capture's HDRI, with contact shadow (sun direction matches the sky)
4. CG-over-plate composite (A-over-B)

`render_meta.json` is the actual run output (azimuth 265°, alignment MSE 0.52 vs ~1.0 off-axis — a real minimum).

## Reproduce (assets + plate are scratch/regenerable; not committed)

```bash
# 1. matched HDRI (25 MB, CC0)
curl -L "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/kloofendal_43d_clear_4k.hdr" -o /tmp/k.hdr
# 2. tonemap -> LDR equirect, then cut the plate (see scripts/pano_to_plate.py)
# 3. render the CG insert lit by the HDRI (Blender, CPU ~30s):
blender -b -P scripts/render_cg_insert.py -- \
  --hdr /tmp/k.hdr --plate /tmp/plate/plate_rgb.png \
  --extraction-manifest /tmp/plate/plate_extraction.json --out-dir /tmp/cg_out
# 4. assemble + validate:
.venv/bin/python scripts/assemble_fixture.py --plate /tmp/plate/plate_rgb.png \
  --out-dir /tmp/fx/case1 --fixture-id case1 --cg /tmp/cg_out/cg_rgba.png \
  --extraction-manifest /tmp/plate/plate_extraction.json
.venv/bin/python scripts/validate_photographic_fixtures.py --fixtures-root /tmp/fx --min-count 1
```

Implication: on a DiMo L1 YES (issue #3 — does a rectilinear crop of a CC0
equirect photo-panorama count as a real photographic plate?), fixtures #2–#5 are
now pure repetition of a proven pipeline, not new engineering. The CG-over-plate
step is also required on the NO path (DiMo footage + HDRI), so this tool is not
gated on the ruling.
