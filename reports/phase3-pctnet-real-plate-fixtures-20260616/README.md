# Phase 3 PCT-Net Blender Smoke Fixtures - 2026-06-16

> ⚠️ **SMOKE ONLY — NOT QUALITY EVIDENCE**
> The plate in `smoke_blender_set/scenes/` is Blender-mediated (EEVEE render), not
> pristine photography. This does NOT satisfy LOCKED L1. These cases exercise
> plumbing only and must never enter a quality table or gate record without the
> `blender_smoke` provenance label.

Source revision: `b381ca6` (`main`, `origin/main`)

## What Ran

Validated the committed real-plate Blender fixtures, rendered fresh transparent
CG layers from the `.blend` files, packaged the corresponding 1280x720 real
photo plates and alpha mattes, then ran the Phase 1 PCT-Net backend.

Commands:

```bash
blender --background --python scripts/validate_smoke_blender_fixtures.py

blender --background fixtures/smoke_blender_set/scenes/smoke_meeting_room_shadow.blend \
  --python-expr "import bpy; bpy.context.scene['validation_out_dir']='reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/meeting_room'" \
  --python reports/phase3-real-plate-validation-20260615/render_blender_inputs.py

blender --background fixtures/smoke_blender_set/scenes/smoke_table_edge_occlusion.blend \
  --python-expr "import bpy; bpy.context.scene['validation_out_dir']='reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/table_edge'" \
  --python reports/phase3-real-plate-validation-20260615/render_blender_inputs.py

CUDA_VISIBLE_DEVICES=0 PYTHONPATH=".deps:." python3 cli/run_phase1.py \
  --config configs/phase1_pctnet.json \
  --plate reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/meeting_room/plate_rgb.png \
  --cg reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/meeting_room/cg_rgba.png \
  --alpha reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/meeting_room/alpha.png \
  --output-dir reports/phase3-pctnet-real-plate-fixtures-20260616/runs/meeting_room_pctnet

CUDA_VISIBLE_DEVICES=0 PYTHONPATH=".deps:." python3 cli/run_phase1.py \
  --config configs/phase1_pctnet.json \
  --plate reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/table_edge/plate_rgb.png \
  --cg reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/table_edge/cg_rgba.png \
  --alpha reports/phase3-pctnet-real-plate-fixtures-20260616/inputs/table_edge/alpha.png \
  --output-dir reports/phase3-pctnet-real-plate-fixtures-20260616/runs/table_edge_pctnet

PYTHONPATH=".deps:." python3 scripts/phase2_rejection_checks.py \
  --job reports/phase3-pctnet-real-plate-fixtures-20260616/runs/meeting_room_pctnet/job.json

PYTHONPATH=".deps:." python3 scripts/phase2_rejection_checks.py \
  --job reports/phase3-pctnet-real-plate-fixtures-20260616/runs/table_edge_pctnet/job.json
```

## Results

| Case | Layer-1 | Plate untouched | Edge seam | Duration | Max reserved VRAM | Mean foreground delta |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| meeting_room | PASS 6/6 | 0.00392 / 0.012 | 1.1362 / 1.25 | 2.2702 s | 162.0 MiB | 0.088647 |
| table_edge | PASS 6/6 | 0.00392 / 0.012 | 1.2297 / 1.25 | 2.2194 s | 162.0 MiB | 0.114724 |

Both jobs preserve the trusted A-over-B contract (`plate_repainted=false`) and
produce the full expected output family.

## Artifacts

- `fixture_validator.log` - Blender fixture validator output.
- `summary_metrics.json` - compact metrics extracted from jobs and Layer-1 checks.
- `pctnet_real_plate_blender_contact_sheet.png` - full still review sheet. ⚠️ SMOKE ONLY — see provenance banner above.
- `pctnet_alpha_edge_review.png` - zoomed alpha-edge review sheet.
- `runs/meeting_room_pctnet/` and `runs/table_edge_pctnet/` - full PCT-Net output families.

## Notes

The table-edge case is a pass, but it is close to the edge-seam ceiling:
`1.2297` against `1.25`. Visual review of the alpha-edge sheet shows visible
foreground color/material movement, especially on the table-edge sphere and
cone. This is useful evidence that PCT-Net is changing the inserted CG, but it
is not a claim of perceptual quality over raw A-over-B.
