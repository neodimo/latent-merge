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
    p.add_argument("--object-distance", type=float, default=5.5)
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
    return scores


def _plate_yaw_to_blender_azimuth(yaw_deg: float) -> float:
    """Map pano_to_plate's +Z-forward/right-handed yaw to Blender's world.

    Blender's level camera at azimuth 0 looks along +Y, while its environment
    texture's longitude increases in the opposite direction to pano_to_plate.
    The resulting basis change is azimuth = 270 - yaw.
    """
    return (270.0 - yaw_deg) % 360.0


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


def render(path: str, w: int, h: int, samples: int, transparent: bool, pct: int = 100) -> None:
    scn = bpy.context.scene
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

    # 3. CG object lit by the HDRI, contact shadow, transparent film
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_world(args.hdr)
    cam = setup_camera(az, pitch, hfov, (0, 0, args.cam_height))
    bpy.context.view_layer.update()
    fwd = (cam.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
    fwd_xy = Vector((fwd.x, fwd.y, 0)).normalized()
    hit = Vector((0, 0, args.cam_height)) + fwd_xy * args.object_distance

    bpy.ops.mesh.primitive_plane_add(size=80, location=(0, 0, 0))
    bpy.context.active_object.is_shadow_catcher = True
    bpy.ops.mesh.primitive_monkey_add(size=1.6, location=(hit.x, hit.y, 0.95))
    obj = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    mat = bpy.data.materials.new("cg")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.85, 0.12, 0.10, 1)
    bsdf.inputs["Roughness"].default_value = 0.30
    obj.data.materials.append(mat)
    render(os.path.join(args.out_dir, "cg_rgba.png"), pw, ph, args.samples, True)

    meta = {
        "hdr": os.path.basename(args.hdr),
        "plate": os.path.basename(args.plate),
        "azimuth_deg": az,
        "pitch_deg": pitch,
        "hfov_deg": hfov,
        "alignment_mse": align_mse,
        "projection_scores": projection_scores,
        "cam_height_m": args.cam_height,
        "object_distance_m": args.object_distance,
        "samples": args.samples,
    }
    json.dump(meta, open(os.path.join(args.out_dir, "render_meta.json"), "w"), indent=2)
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
