#!/usr/bin/env python3
"""Render a matched-HDRI CG insert for a photographic plate (headless Blender).

This is the link between `pano_to_plate.py` and `assemble_fixture.py`. A LOCKED
L1 fixture needs a CG insert that is *lit by the plate's matched HDRI* -- not a
procedural placeholder. Given the panorama HDRI (the same capture the plate was
cropped from) and the plate's `plate_extraction.json` (yaw / pitch / hfov), this
renders a CG object lit by that HDRI as world lighting, with a contact shadow,
on a transparent film, at the plate resolution. The output `cg_rgba.png` drops
straight into `assemble_fixture.py --cg`.

Camera <-> plate alignment is deterministic and inspectable. pano_to_plate's
yaw maps to Blender azimuth as ``270 - yaw`` and its pitch sign is opposite
Blender's camera X rotation. A full-resolution background check plus normalised
pixel scores are written so the convention is verified against the real plate.

Run with Blender (not the project venv):

    blender -b -P scripts/render_cg_insert.py -- \
        --hdr /path/kloofendal_43d_clear_4k.hdr \
        --plate reports/.../plate_rgb.png \
        --extraction-manifest reports/.../plate_extraction.json \
        --out-dir /tmp/cg_out

Outputs in --out-dir: cg_rgba.png (the insert), bg_check.png (alignment proof),
and render_meta.json (chosen azimuth + alignment score).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

try:
    import bpy
    from mathutils import Vector
except ImportError:  # pragma: no cover - only importable inside Blender
    print("render_cg_insert.py must be run inside Blender: blender -b -P ... -- <args>")
    raise SystemExit(2)


def _argv_after_dashes() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hdr", required=True, help="equirect HDRI = the plate's matched capture")
    p.add_argument("--plate", required=True, help="plate_rgb.png used as the alignment target")
    p.add_argument("--extraction-manifest", help="plate_extraction.json (pitch/hfov source)")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--pitch", type=float, default=None, help="override pitch_deg")
    p.add_argument("--hfov", type=float, default=None, help="override hfov_deg")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--cam-height", type=float, default=1.6)
    p.add_argument("--place-uv", type=float, nargs=2, default=[0.5, 0.80],
                   metavar=("U", "V"),
                   help="normalised plate pixel (u from left, v from top) where the object "
                        "TOUCHES the ground. Must be below the horizon.")
    p.add_argument("--object-height", type=float, default=None,
                   help="object height in metres; default 0.55 * cam-height")
    p.add_argument("--verify-ground", action="store_true",
                   help="also write ground_grid.png / ground_check.png overlaying the solved "
                        "ground plane on the plate")
    p.add_argument("--asset", default="suzanne",
                   choices=("suzanne", "gray_ball", "ref_balls"),
                   help="suzanne = placeholder; gray_ball = 18%% matte sphere; ref_balls = "
                        "the on-set pair, 18%% matte + chrome, for reading the lighting ratio "
                        "and the environment without a coloured material in the way")
    p.add_argument("--view-transform", default="AgX",
                   help="OCIO view transform; MUST match the one the plate was tonemapped "
                        "with (scripts/tonemap_pano.py), default AgX")
    p.add_argument("--look", default="None")
    p.add_argument("--exposure", type=float, default=0.0)
    p.add_argument("--gamma", type=float, default=1.0)
    p.add_argument("--diagnose-projection", action="store_true",
                   help="render mapped manifest yaw, score mirror variants, then exit")
    return p.parse_args(_argv_after_dashes())


def _view_from_manifest(path: str | None) -> tuple[float, float]:
    pitch, hfov = -5.0, 75.0
    if path and os.path.exists(path):
        view = json.load(open(path)).get("view", {})
        pitch = float(view.get("pitch_deg", pitch))
        hfov = float(view.get("hfov_deg", hfov))
    return pitch, hfov


def _yaw_from_manifest(path: str | None) -> float:
    if path and os.path.exists(path):
        return float(json.load(open(path)).get("view", {}).get("yaw_deg", 0.0))
    return 0.0


def _load_gray(path: str) -> np.ndarray:
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:]).reshape(h, w, img.channels)
    bpy.data.images.remove(img)
    return px[..., :3].mean(2)[::-1]  # Blender pixel buffer is bottom-up


def _image_size(path: str) -> tuple[int, int]:
    img = bpy.data.images.load(path)
    w, h = img.size
    bpy.data.images.remove(img)
    return int(w), int(h)


def _downsample(a: np.ndarray, w: int, h: int) -> np.ndarray:
    ys = np.linspace(0, a.shape[0] - 1, h).astype(int)
    xs = np.linspace(0, a.shape[1] - 1, w).astype(int)
    return a[np.ix_(ys, xs)]


def _norm(a: np.ndarray) -> np.ndarray:
    return (a - a.mean()) / (a.std() + 1e-6)


def _projection_scores(plate: np.ndarray, rendered: np.ndarray) -> dict[str, dict[str, float]]:
    """Score orientation variants after removing tone/contrast as confounds."""
    variants = {
        "identity": plate,
        "mirror_horizontal": plate[:, ::-1],
        "mirror_vertical": plate[::-1],
        "mirror_both": plate[::-1, ::-1],
    }
    rendered_n = _norm(rendered)
    scores = {}
    for name, candidate in variants.items():
        candidate_n = _norm(candidate)
        mse = float(np.mean((candidate_n - rendered_n) ** 2))
        scores[name] = {"mse": mse, "correlation": 1.0 - mse / 2.0}
    # The normalised scores deliberately remove tone so geometry can be judged
    # on its own. Tone agreement therefore needs its own un-normalised check:
    # once plate and render share a view transform, these should be small.
    scores["identity"]["raw_mse"] = float(np.mean((plate - rendered) ** 2))
    scores["identity"]["raw_mean_delta"] = float(plate.mean() - rendered.mean())
    scores["identity"]["raw_std_ratio"] = float(plate.std() / (rendered.std() + 1e-9))
    return scores


def _plate_yaw_to_blender_azimuth(yaw_deg: float) -> float:
    """Map pano_to_plate's +Z-forward/right-handed yaw to Blender's world.

    Blender's level camera at azimuth 0 looks along +Y, while its environment
    texture's longitude increases in the opposite direction to pano_to_plate.
    The resulting basis change is azimuth = 270 - yaw.
    """
    return (270.0 - yaw_deg) % 360.0


def ground_hit_from_pixel(cam, u: float, v: float, hfov: float, aspect: float,
                          ground_z: float = 0.0) -> "Vector":
    """Unproject a plate pixel and intersect the solved ground plane.

    The insertion point has to be a place the viewer can actually see in the
    plate, so it is specified in image space and pushed out into the world,
    rather than guessed as a distance along the camera's forward axis. A pixel
    on or above the horizon has no ground behind it and is a hard error, not a
    silently clamped placement.
    """
    half_w = math.tan(math.radians(hfov) / 2.0)
    half_h = half_w * aspect
    d_cam = Vector(((u - 0.5) * 2.0 * half_w, (0.5 - v) * 2.0 * half_h, -1.0))
    d_world = (cam.matrix_world.to_3x3() @ d_cam).normalized()
    if d_world.z > -1e-4:
        raise SystemExit(
            f"place-uv ({u}, {v}) points at or above the horizon: that pixel shows sky or "
            f"distant background, not ground. Pick a pixel on the visible surface."
        )
    t = (ground_z - cam.location.z) / d_world.z
    return cam.location + d_world * t


def rest_on_ground(obj, hit: "Vector", target_height: float | None = None,
                   ground_z: float = 0.0) -> dict:
    """Scale to a real-world height, then seat the object's footprint on the plane.

    Contact is derived from the object's own world bounding box, so the object
    touches the ground for any mesh at any rotation instead of relying on a
    hand-tuned Z that only ever suits one asset.
    """
    def world_bbox():
        pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        return lo, hi

    bpy.context.view_layer.update()
    lo, hi = world_bbox()
    if target_height:
        scale = target_height / max(hi.z - lo.z, 1e-6)
        obj.scale = tuple(s * scale for s in obj.scale)
        bpy.context.view_layer.update()
        lo, hi = world_bbox()
    obj.location += Vector((
        hit.x - (lo.x + hi.x) / 2.0,
        hit.y - (lo.y + hi.y) / 2.0,
        ground_z - lo.z,
    ))
    bpy.context.view_layer.update()
    lo, hi = world_bbox()
    return {
        "contact_point_world": [round(hit.x, 4), round(hit.y, 4), round(hit.z, 4)],
        "bbox_min_z": round(lo.z, 6),
        "bbox_height_m": round(hi.z - lo.z, 4),
        "camera_distance_m": round((hit - bpy.context.scene.camera.location).length, 3),
    }


def add_ground(shadow_catcher: bool = True, grid: bool = False) -> "bpy.types.Object":
    """The plate's ground plane. Either an invisible shadow receiver or, for the
    verification pass, a visible 1 m grid used to check the plane against the
    surface the photograph actually shows."""
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    plane = bpy.context.active_object
    if shadow_catcher:
        plane.is_shadow_catcher = True
        return plane
    if grid:
        mat = bpy.data.materials.new("grid")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        coord = nt.nodes.new("ShaderNodeTexCoord")
        checker = nt.nodes.new("ShaderNodeTexChecker")
        checker.inputs["Scale"].default_value = 1.0
        checker.inputs["Color1"].default_value = (0.9, 0.15, 0.15, 1)
        checker.inputs["Color2"].default_value = (0.05, 0.55, 0.95, 1)
        emit = nt.nodes.new("ShaderNodeEmission")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(coord.outputs["Object"], checker.inputs["Vector"])
        nt.links.new(checker.outputs["Color"], emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
        plane.data.materials.append(mat)
    return plane


def blend_over(base_path: str, overlay_path: str, out_path: str, alpha: float = 0.45) -> None:
    """Write an overlay contact sheet: the grid render composited on the plate."""
    base = bpy.data.images.load(base_path)
    over = bpy.data.images.load(overlay_path)
    w, h = base.size
    b = np.array(base.pixels[:]).reshape(-1, base.channels)[:, :3]
    o = np.array(over.pixels[:]).reshape(-1, over.channels)
    a = (o[:, 3:4] if over.channels == 4 else np.ones((o.shape[0], 1))) * alpha
    rgb = b * (1 - a) + o[:, :3] * a
    img = bpy.data.images.new("overlay", w, h, alpha=False)
    img.pixels = np.concatenate([rgb, np.ones((rgb.shape[0], 1))], 1).ravel().tolist()
    img.filepath_raw = out_path
    img.file_format = "PNG"
    img.save()
    for i in (base, over, img):
        bpy.data.images.remove(i)


def _matte(name: str, albedo: float) -> "bpy.types.Material":
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (albedo, albedo, albedo, 1)
    b.inputs["Roughness"].default_value = 1.0
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = 0.0
    return mat


def _chrome(name: str) -> "bpy.types.Material":
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (1, 1, 1, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.02
    return mat


def build_asset(kind: str, height: float) -> "bpy.types.Object":
    """The mesh to insert.

    A saturated coloured placeholder hides whether the lighting ratio is right,
    so the reference options are the on-set pair: an 18% matte sphere, whose
    shading gradient is readable against the plate's own midtones, and a chrome
    sphere, whose reflection of the environment can be compared directly with
    the surrounding plate pixels. Both are neutral, so anything ugly in the
    result is the light or the tone path, not the material.
    """
    if kind == "suzanne":
        bpy.ops.mesh.primitive_monkey_add(size=1.0, location=(0, 0, 0))
        obj = bpy.context.active_object
        bpy.ops.object.shade_smooth()
        mat = bpy.data.materials.new("cg")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (0.85, 0.12, 0.10, 1)
        bsdf.inputs["Roughness"].default_value = 0.30
        obj.data.materials.append(mat)
        return obj

    r = height / 2.0
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=64, ring_count=32,
                                         location=(0, 0, 0))
    gray = bpy.context.active_object
    gray.name = "gray_ball"
    bpy.ops.object.shade_smooth()
    gray.data.materials.append(_matte("matte18", 0.18))
    if kind == "gray_ball":
        return gray

    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=64, ring_count=32,
                                         location=(0, 0, 0))
    chrome = bpy.context.active_object
    chrome.name = "chrome_ball"
    bpy.ops.object.shade_smooth()
    chrome.data.materials.append(_chrome("chrome"))
    # Offset along local +X by 1.35 diameters; the pair is then seated as one
    # unit so both spheres touch the same ground plane.
    chrome.location.x = r * 2.7
    for o in (gray, chrome):
        o.select_set(True)
    bpy.context.view_layer.objects.active = gray
    bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = "ref_balls"
    return joined


def prune_stray_alpha(path: str, seed_level: float = 0.5, keep_level: float = 0.015,
                      max_iters: int = 400) -> dict:
    """Keep only the alpha that is connected to the object, and zero the rest.

    A shadow catcher sprays low-amplitude sampling speckle over the whole plane,
    and every one of those pixels would modify plate pixels outside the
    interaction region, which the trust contract forbids. Connectivity is used
    rather than a radius so a genuinely long cast shadow survives intact while
    isolated noise does not.
    """
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:]).reshape(h, w, 4)
    a = px[..., 3]
    region = a > keep_level
    seed = a > seed_level
    if not seed.any():
        bpy.data.images.remove(img)
        return {"pruned_pixels": 0, "note": "no opaque seed found"}
    for _ in range(max_iters):
        grown = seed.copy()
        for shifted in (
            np.roll(seed, 1, 0), np.roll(seed, -1, 0),
            np.roll(seed, 1, 1), np.roll(seed, -1, 1),
        ):
            grown |= shifted
        grown &= region
        if grown.sum() == seed.sum():
            break
        seed = grown
    stray = region & ~seed
    px[..., 3] = np.where(seed | (a > seed_level), a, 0.0)
    img.pixels = px.ravel().tolist()
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return {
        "pruned_pixels": int(stray.sum()),
        "kept_alpha_pixels": int(seed.sum()),
        "stray_alpha_max": round(float(a[stray].max()) if stray.any() else 0.0, 4),
    }


def setup_world(hdr: str) -> None:
    scn = bpy.context.scene
    scn.world = bpy.data.worlds.new("W")
    scn.world.use_nodes = True
    nt = scn.world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(hdr)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def setup_camera(az: float, pitch: float, hfov: float, loc) -> "bpy.types.Object":
    cd = bpy.data.cameras.new("C")
    cd.sensor_fit = "HORIZONTAL"
    cd.sensor_width = 36.0
    cd.lens = (cd.sensor_width / 2.0) / math.tan(math.radians(hfov) / 2.0)
    cam = bpy.data.objects.new("Cam", cd)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = Vector(loc)
    # rot_x=90 aims camera -Z at the horizon. pano_to_plate defines negative
    # pitch as looking up, hence Blender's X rotation uses 90 - pitch.
    cam.rotation_euler = (math.radians(90.0 - pitch), 0.0, math.radians(az))
    bpy.context.scene.camera = cam
    return cam


# Pinned at startup from the CLI and re-applied before every write, because
# each scene reset restores factory colour management. The plate and the render
# must leave the pipeline through one view transform or they are not comparable.
VIEW: dict = {"view_transform": "AgX", "look": "None", "exposure": 0.0, "gamma": 1.0}


def apply_view_settings() -> dict:
    scn = bpy.context.scene
    scn.display_settings.display_device = "sRGB"
    vs = scn.view_settings
    try:
        vs.view_transform = VIEW["view_transform"]
    except TypeError as exc:
        raise SystemExit(
            f"view transform {VIEW['view_transform']!r} not in this OCIO config: {exc}"
        )
    try:
        vs.look = VIEW["look"]
    except TypeError:
        vs.look = "None"
    vs.exposure = VIEW["exposure"]
    vs.gamma = VIEW["gamma"]
    return {
        "view_transform": vs.view_transform, "look": vs.look,
        "exposure": vs.exposure, "gamma": vs.gamma,
        "display_device": scn.display_settings.display_device,
    }


def render(path: str, w: int, h: int, samples: int, transparent: bool, pct: int = 100) -> None:
    scn = bpy.context.scene
    apply_view_settings()
    scn.render.engine = "CYCLES"
    try:
        scn.cycles.device = "CPU"
    except Exception:
        pass
    scn.cycles.samples = samples
    try:
        scn.cycles.use_denoising = True
    except Exception:
        pass
    scn.render.resolution_x, scn.render.resolution_y = w, h
    scn.render.resolution_percentage = pct
    scn.render.film_transparent = transparent
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    scn.render.resolution_percentage = 100


def main() -> int:
    args = parse_args()
    VIEW.update(view_transform=args.view_transform, look=args.look,
                exposure=args.exposure, gamma=args.gamma)
    pitch, hfov = _view_from_manifest(args.extraction_manifest)
    manifest_yaw = _yaw_from_manifest(args.extraction_manifest)
    if args.pitch is not None:
        pitch = args.pitch
    if args.hfov is not None:
        hfov = args.hfov
    os.makedirs(args.out_dir, exist_ok=True)
    pw, ph = _image_size(args.plate)

    # 1. find the world azimuth that aligns the HDRI background to the plate
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_world(args.hdr)
    setup_camera(0.0, pitch, hfov, (0, 0, args.cam_height))

    if args.diagnose_projection:
        mapped_azimuth = _plate_yaw_to_blender_azimuth(manifest_yaw)
        diagnostic_path = os.path.join(args.out_dir, "bg_mapped_yaw.png")
        bpy.context.scene.objects["Cam"].rotation_euler = (
            math.radians(90 - pitch), 0, math.radians(mapped_azimuth)
        )
        render(diagnostic_path, pw, ph, 16, False)
        plate_s = _downsample(_load_gray(args.plate), 320, 180)
        render_s = _downsample(_load_gray(diagnostic_path), 320, 180)
        result = {
            "manifest_yaw_deg": manifest_yaw,
            "blender_azimuth_deg": mapped_azimuth,
            "pitch_deg": pitch,
            "hfov_deg": hfov,
            "scores": _projection_scores(plate_s, render_s),
        }
        json.dump(result, open(os.path.join(args.out_dir, "projection_diagnostic.json"), "w"), indent=2)
        print(json.dumps(result, indent=2))
        return 0

    # The projection convention is deterministic. Searching was both slower
    # and unreliable when plate/render tone curves differed strongly.
    az = _plate_yaw_to_blender_azimuth(manifest_yaw)
    print(f"MAPPED_AZ {az} from plate yaw {manifest_yaw}")

    # 2. full-res background render at the chosen azimuth (alignment evidence)
    bpy.context.scene.objects["Cam"].rotation_euler = (math.radians(90 - pitch), 0, math.radians(az))
    bg_check_path = os.path.join(args.out_dir, "bg_check.png")
    render(bg_check_path, pw, ph, 16, False)
    projection_scores = _projection_scores(
        _downsample(_load_gray(args.plate), 320, 180),
        _downsample(_load_gray(bg_check_path), 320, 180),
    )
    align_mse = projection_scores["identity"]["mse"]

    # 3. solve where the chosen plate pixel meets the ground plane
    u, v = args.place_uv
    aspect = ph / pw
    obj_height = args.object_height or 0.55 * args.cam_height

    # 3a. verification pass: is the solved plane on the surface the plate shows?
    if args.verify_ground:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        setup_world(args.hdr)
        cam = setup_camera(az, pitch, hfov, (0, 0, args.cam_height))
        bpy.context.view_layer.update()
        add_ground(shadow_catcher=False, grid=True)
        grid_path = os.path.join(args.out_dir, "ground_grid.png")
        render(grid_path, pw, ph, 8, True)
        blend_over(args.plate, grid_path, os.path.join(args.out_dir, "ground_check.png"))

    # 3b. CG object lit by the HDRI, seated on the ground, shadow into the plate
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_world(args.hdr)
    cam = setup_camera(az, pitch, hfov, (0, 0, args.cam_height))
    bpy.context.view_layer.update()
    hit = ground_hit_from_pixel(cam, u, v, hfov, aspect)

    add_ground(shadow_catcher=True)
    obj = build_asset(args.asset, obj_height)
    placement = rest_on_ground(obj, hit, target_height=obj_height)
    print("PLACEMENT " + json.dumps(placement))
    mat = bpy.data.materials.new("cg")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.85, 0.12, 0.10, 1)
    bsdf.inputs["Roughness"].default_value = 0.30
    obj.data.materials.append(mat)
    cg_path = os.path.join(args.out_dir, "cg_rgba.png")
    render(cg_path, pw, ph, args.samples, True)
    prune = prune_stray_alpha(cg_path)
    print("ALPHA_PRUNE " + json.dumps(prune))

    meta = {
        "hdr": os.path.basename(args.hdr),
        "plate": os.path.basename(args.plate),
        "azimuth_deg": az,
        "pitch_deg": pitch,
        "hfov_deg": hfov,
        "alignment_mse": align_mse,
        "projection_scores": projection_scores,
        "cam_height_m": args.cam_height,
        "place_uv": [u, v],
        "asset": args.asset,
        "object_height_m": obj_height,
        "placement": placement,
        "alpha_prune": prune,
        "color_management": apply_view_settings(),
        "samples": args.samples,
    }
    json.dump(meta, open(os.path.join(args.out_dir, "render_meta.json"), "w"), indent=2)
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
