"""Difference-based plate composite: derive the object's ground interaction from a pair.

Run inside Blender:
    blender -b -P scripts/composite_difference.py -- \
        --hdr <hdri> --plate <plate_rgb.png> --out-dir <dir>

Why this exists
---------------
`reports/ground-proxy-production-20260815/` rejected the shadow-catcher-plus-proxy
composite on pixels, and `reports/proxy-isolation-20260815/` attributed the defect:
the Cycles shadow catcher computes its plate merge as a shadowing ratio against
*any* object that occludes it, so a coincident camera-hidden transport proxy gets
written into the plate as a cast shadow over the whole ground plane.

This path removes the shadow catcher entirely. The ground is an ordinary matte
surface, rendered twice — once with the object, once without — and the object's
effect on it is the ratio between the two:

    ratio = ground_with_object / ground_alone

Anything the ground does on its own appears identically in both halves and
divides out. That is the property the isolation pass measured: over the footprint
pixels the object never touches, this ratio sat 0.000161 from 1.0 while the
additive veil it replaces was 0.017448 — 108.6x suppression. The veil cannot come
back through this construction, because nothing static survives a ratio against
itself.

The object itself is rendered separately over transparent film with the ground
kept camera-hidden but ray-visible, so it is lit by the same bounce it casts onto.

Three renders, one scene construction, all linear EXR with a pinned seed and the
denoiser off — a ratio between two denoised images is not a ratio between two
renders.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

try:
    import bpy
    import numpy as np
except ImportError:  # pragma: no cover - only importable inside Blender
    print("composite_difference.py must be run inside Blender: blender -b -P ... -- <args>")
    raise SystemExit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_render_module():
    path = os.path.join(ROOT, "scripts", "render_cg_insert.py")
    spec = importlib.util.spec_from_file_location("rci", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _argv_after_dashes() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hdr", required=True)
    p.add_argument("--plate", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--yaw", type=float, default=None)
    p.add_argument("--pitch", type=float, default=-6.0)
    p.add_argument("--hfov", type=float, default=72.0)
    p.add_argument("--place-uv", type=float, nargs=2, default=[0.42, 0.88])
    p.add_argument("--cam-height", type=float, default=1.6)
    p.add_argument("--object-height", type=float, default=0.45)
    p.add_argument("--asset", default="ref_balls")
    p.add_argument("--ground-albedo", type=float, default=0.08)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--ratio-max", type=float, default=4.0,
                   help="clamp on the interaction ratio; guards the divide where the "
                        "ground render is near black")
    return p.parse_args(_argv_after_dashes())


def _yaw_beside_plate(plate: str, override: float | None) -> float:
    if override is not None:
        return override
    manifest = os.path.join(os.path.dirname(plate), "plate_extraction.json")
    if not os.path.exists(manifest):
        raise SystemExit(f"no --yaw given and no extraction manifest at {manifest}")
    data = json.load(open(manifest))
    for scope in (data.get("view", {}), data):
        for key in ("yaw_deg", "yaw", "center_yaw_deg"):
            if key in scope:
                return float(scope[key])
    raise SystemExit(f"{manifest} has no yaw field; pass --yaw")


def _read(path: str) -> np.ndarray:
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, img.channels)[::-1]
    bpy.data.images.remove(img)
    return px.copy()


def _srgb_to_linear(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def _write_png(path: str, rgb: np.ndarray) -> None:
    h, w = rgb.shape[:2]
    img = bpy.data.images.new(os.path.basename(path), w, h, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "sRGB"
    flat = np.concatenate([rgb[::-1], np.ones((h, w, 1), np.float32)], axis=2)
    img.pixels = flat.ravel().tolist()
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def build(rci, args, mode: str):
    """`ground_only` and `ground_object` differ by exactly one thing: the object.
    `object_only` swaps the visible ground for the camera-hidden transport proxy
    so the object is lit by the same surface it stands on but the surface is not
    drawn into its alpha."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rci.setup_world(args.hdr)
    az = rci._plate_yaw_to_blender_azimuth(args.yaw)
    cam = rci.setup_camera(az, args.pitch, args.hfov, (0, 0, args.cam_height))
    bpy.context.view_layer.update()
    hit = rci.ground_hit_from_pixel(cam, *args.place_uv, args.hfov, args.height / args.width)

    if mode == "object_only":
        proxy = rci.add_light_proxy(args.ground_albedo, "ground_light_proxy")
        rci.assert_light_proxy_contract(proxy)
    else:
        # An ordinary visible matte surface. No shadow catcher anywhere in this
        # path; the plate merge comes from the ratio, not from Cycles.
        ground = rci.add_ground(shadow_catcher=False)
        ground.name = "ground_matte"
        ground.data.materials.append(rci._matte("ground_matte", args.ground_albedo))

    if mode == "ground_only":
        return {"mode": mode, "azimuth_deg": az}

    obj = rci.build_asset(args.asset, args.object_height)
    # Orient before seating: the rotation changes the world bounding box that
    # rest_on_ground uses to find the contact point.
    pair_yaw = rci.orient_across_view(obj, hit) if args.asset == "ref_balls" else None
    placement = rci.rest_on_ground(obj, hit, target_height=args.object_height)
    return {"mode": mode, "azimuth_deg": az, "pair_yaw_deg": pair_yaw,
            "placement": placement}


def main() -> int:
    args = parse_args()
    args.yaw = _yaw_beside_plate(args.plate, args.yaw)
    os.makedirs(args.out_dir, exist_ok=True)
    rci = _load_render_module()

    frames, infos = {}, {}
    for mode in ("ground_only", "ground_object", "object_only"):
        infos[mode] = build(rci, args, mode)
        path = os.path.join(args.out_dir, f"{mode}.exr")
        rci.render(path, args.width, args.height, args.samples,
                   transparent=(mode == "object_only"),
                   linear=True, denoise=False, seed=args.seed)
        frames[mode] = _read(path)
        print(f"RENDERED {mode}")

    plate = _read(args.plate)[..., :3]
    if plate.shape[:2] != (args.height, args.width):
        raise SystemExit(f"plate is {plate.shape[1]}x{plate.shape[0]}, render is "
                         f"{args.width}x{args.height}; they must match")
    # The plate is a delivered LDR sRGB image, so it is decoded with the sRGB
    # curve. This is an approximation: the ratio is a light-transport quantity
    # and wants true scene-linear plate values, which an already-tonemapped
    # plate cannot give back. Recorded as a caveat rather than hidden.
    plate_lin = _srgb_to_linear(plate)

    a, b = frames["ground_object"][..., :3], frames["ground_only"][..., :3]
    eps = 1e-6
    ratio = np.clip((a + eps) / (b + eps), 0.0, args.ratio_max)

    obj = frames["object_only"]
    obj_rgb, obj_a = obj[..., :3], obj[..., 3:4]

    # Where the object is opaque the ratio is meaningless - it is the object's
    # own pixels divided by the ground behind it - so the object composite must
    # cover it. Alpha does that, and the ratio is only trusted where alpha is low.
    out_lin = plate_lin * ratio * (1.0 - obj_a) + obj_rgb  # obj is premultiplied
    out = _linear_to_srgb(out_lin)
    _write_png(os.path.join(args.out_dir, "composite.png"), out.astype(np.float32))

    # The interaction on its own, as a visible artifact: what this composite
    # actually did to the plate, with the object taken out of it.
    interaction = np.clip(ratio, 0, 2) / 2.0
    _write_png(os.path.join(args.out_dir, "interaction_ratio.png"),
               _linear_to_srgb(interaction).astype(np.float32))

    lum = lambda x: 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]
    plate_side = (obj_a[..., 0] < 0.01)
    rl = lum(ratio)[plate_side]
    touched = np.abs(rl - 1.0) > 0.02
    delta = lum(out_lin) - lum(plate_lin)

    report = {
        "hdr": os.path.basename(args.hdr),
        "plate": os.path.basename(args.plate),
        "method": "difference ratio; no shadow catcher",
        "yaw_deg": args.yaw, "pitch_deg": args.pitch, "hfov_deg": args.hfov,
        "resolution": [args.width, args.height],
        "samples": args.samples, "seed": args.seed, "denoising": False,
        "ratio_max": args.ratio_max,
        "modes": infos,
        "plate_pixels": int(plate_side.sum()),
        "ratio_mean_off_object": round(float(rl.mean()), 6),
        "ratio_p01_off_object": round(float(np.percentile(rl, 1)), 6),
        "plate_modified_fraction": round(float(touched.mean()), 6),
        "plate_delta_mean_abs_off_object": round(float(np.abs(delta)[plate_side].mean()), 6),
        "object_coverage": round(float((obj_a[..., 0] > 0.5).mean()), 6),
        "plate_decode": "sRGB EOTF; approximation, the plate is already tonemapped",
    }
    json.dump(report, open(os.path.join(args.out_dir, "composite_meta.json"), "w"), indent=2)
    print("DIFFERENCE_COMPOSITE " + json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
