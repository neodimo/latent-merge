# Ground contact: the CG object now sits on the surface the plate shows

DiMo, 2026-08-14 (#latent-merge): *"the 3d object needs to be sitting/laying on
the perceived surface/ground that is viewable in the image, and shadows and
other integrations need to live within that world."*

## What changed in `scripts/render_cg_insert.py`

Before, insertion was `walk 5.5 m down the camera's forward axis, park the mesh
at z=0.95`. Nothing tied that to anything visible in the plate, and the object
did not touch the plane it was casting onto.

1. **Contact is now a plate pixel.** `--place-uv U V` names the pixel where the
   object touches the ground. The ray through that pixel is unprojected and
   intersected with the ground plane (`ground_hit_from_pixel`). A pixel on or
   above the horizon is a hard error — a placement request that has no visible
   ground behind it fails loudly instead of being silently clamped.
2. **Seating is derived, not guessed.** `rest_on_ground` scales the mesh to a
   real height (`--object-height`, metres) and offsets it so its world bounding
   box floor equals the ground plane, for any mesh at any rotation.
   `render_meta.json` records `bbox_min_z`, which must be 0.
3. **The plane is verified against the photograph, not assumed.**
   `--verify-ground` renders the solved plane as an emissive 1 m grid and blends
   it over the plate (`ground_check.png`). The plane's convergence and horizon
   are then something we look at.
4. **The shadow stays inside the interaction region.** `prune_stray_alpha` keeps
   only alpha connected to the object and zeroes the rest, so shadow-catcher
   sampling speckle cannot modify plate pixels elsewhere. Connectivity, not a
   radius, so a long cast shadow survives intact.

## Evidence (this run)

Case: Poly Haven `urban_alley_01`, yaw 0 / pitch -6 / hfov 72, 1920x1080,
256 samples, CPU Cycles, `--place-uv 0.42 0.88 --object-height 1.1`.

- `bbox_min_z` = **0.0** — the mesh touches the plane.
- Contact solved to `(8.04, 0.91, 0)`, 8.25 m from camera, from the requested
  pixel.
- Alpha prune: 72 stray pixels removed, 63 869 kept; `stray_alpha_max` 0.0.
- Composite modifies **3.08 %** of plate pixels, all connected to the object.
- Background alignment unchanged and still correct: identity correlation 0.986
  vs 0.064 / 0.193 / 0.039 for the three mirrors.

`ground_contact_sheet.png` — plate, grid overlay, composite, contact zoom.
The grid's horizon lands on the plate's, and the alley reads ~4 tiles (~4 m)
wide at the parked car, so the 1.6 m camera height gives a scale consistent
with the photograph.

## What is still wrong — stated, not hidden

- **The world is one infinite flat plane.** The grid runs straight through the
  parked car and up the shopfronts. Nothing can occlude the object and shadows
  cannot climb a wall or stop at the car. This is the next real gap in "living
  within that world": proxy occluder/wall geometry.
- **No curb.** The plate's sidewalk is raised roughly a step above the road; the
  single plane does not model it, so an object placed on the sidewalk sits a
  curb-height low.
- **The asset is still an untextured Suzanne** balancing on her chin. The
  seating is geometrically correct and visually absurd. LOCKED L4 identity
  preservation still has nothing to test until a textured asset with a real
  resting base replaces it.
- **The object's shading does not belong to the scene yet** — flat and pink
  against an overcast alley. That is the relight stage, not placement.

## Next owner + artifact

Gonzo. Next action is proxy scene geometry (ground + wall planes + a coarse
occluder for the parked car) driven from the same camera solve, verified with
the same `--verify-ground` overlay. Then swap in a textured asset and rebuild
the tranche via `scripts/build_intake_tranche.py`.

## Failure mode recorded

Placement was expressed in camera-relative metres, a space nobody can check
against the photograph, which is why "floating Suzanne" survived several
sessions of otherwise careful work. Insertion parameters must be expressed in
the space where the error is visible — image pixels — and every geometric
assumption needs a render that puts it on top of the plate.
