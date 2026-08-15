"""Three-ball light-field regression: does the insert live in the right light?

Run inside Blender:
    blender -b -P tests/light_field_regression.py -- --hdr <hdri> --out-dir <dir>

Why this test exists
--------------------
Bert, 2026-08-15 (#latent-merge): *"keep the three-ball comparison as a
regression fixture. It's the first test here that catches 'object touches the
plate but lives in the wrong light field' without relying on Suzanne's weird
material."*

Everything else in this repo checks geometry (does the object touch the plane?)
or tone (do plate and render share a curve?). Both can pass while the object is
lit by an illumination field the scene could never produce, and a saturated
placeholder material compresses the shading range until that is unreadable. An
18% matte sphere is the instrument that makes it measurable.

The invariant
-------------
**A ground plane can only ever remove light from an object's lower hemisphere.**
It occludes part of the environment and bounces back a fraction of what it
receives; for any ground darker than the environment below the horizon, the net
must be a decrease. So:

    bottom_luminance(with_ground) <= bottom_luminance(no_ground)

This currently FAILS with `is_shadow_catcher`, which is the open bug recorded in
`reports/refball-tone-probe-20260815/`: a Cycles shadow catcher bounces indirect
light without occluding the background, so the environment's lower hemisphere
lights the object straight through the ground it stands on.

Exit code 0 = production holds and the legacy violation remains a named
known-fail. Exit 1 = production violates the invariant or the baseline stops
reproducing the historical bug.
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
    print("light_field_regression.py must be run inside Blender: blender -b -P ... -- <args>")
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
    p.add_argument("--out-dir", required=True)
    p.add_argument("--yaw", type=float, default=0.0)
    p.add_argument("--pitch", type=float, default=-6.0)
    p.add_argument("--hfov", type=float, default=72.0)
    p.add_argument("--place-uv", type=float, nargs=2, default=[0.42, 0.88])
    p.add_argument("--ball-height", type=float, default=0.6)
    p.add_argument("--cam-height", type=float, default=1.6)
    p.add_argument("--samples", type=int, default=192)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--ground-albedo", type=float, default=0.08)
    return p.parse_args(_argv_after_dashes())


def measure(rci, args, mode: str) -> dict:
    """Render an 18% matte sphere over one ground mode and split it top/bottom."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rci.setup_world(args.hdr)
    az = rci._plate_yaw_to_blender_azimuth(args.yaw)
    cam = rci.setup_camera(az, args.pitch, args.hfov, (0, 0, args.cam_height))
    bpy.context.view_layer.update()
    u, v = args.place_uv
    hit = rci.ground_hit_from_pixel(cam, u, v, args.hfov, args.height / args.width)

    if mode == "shadow_catcher":
        rci.add_ground(shadow_catcher=True)
    elif mode == "matte_ground":
        plane = rci.add_ground(shadow_catcher=False)
        plane.data.materials.append(rci._matte("road", args.ground_albedo))
    elif mode == "split":
        # Bert's proposal, measured rather than assumed: the catcher keeps doing
        # the plate merge, and a coincident matte proxy that is hidden from
        # camera but visible to diffuse/glossy rays does the light blocking and
        # bouncing the catcher will not do. Shadow visibility is off on the
        # proxy so the cast shadow is not counted twice.
        rci.add_ground(shadow_catcher=True)
        proxy = rci.add_light_proxy(args.ground_albedo, "light_proxy")
        rci.assert_light_proxy_contract(proxy)
    elif mode != "no_ground":
        raise SystemExit(f"unknown ground mode {mode!r}")

    ball = rci.build_asset("gray_ball", args.ball_height)
    placement = rci.rest_on_ground(ball, hit, target_height=args.ball_height)

    path = os.path.join(args.out_dir, f"ball_{mode}.png")
    rci.render(path, args.width, args.height, args.samples, True)

    img = bpy.data.images.load(path)
    px = np.array(img.pixels[:]).reshape(args.height, args.width, 4)[::-1]
    bpy.data.images.remove(img)
    # Only fully opaque pixels, so the shadow and the antialiased rim cannot
    # drag the sphere's own luminance around.
    mask = px[..., 3] > 0.95
    if not mask.any():
        raise SystemExit(f"{mode}: sphere did not render")
    lum = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    ys = np.nonzero(mask)[0]
    y0, y1 = ys.min(), ys.max()
    third = max((y1 - y0) // 3, 1)
    top = mask.copy(); top[y0 + third:] = False
    bottom = mask.copy(); bottom[: y1 - third] = False
    return {
        "mode": mode,
        "mean": round(float(lum[mask].mean()), 6),
        "top": round(float(lum[top].mean()), 6),
        "bottom": round(float(lum[bottom].mean()), 6),
        "top_over_bottom": round(float(lum[top].mean() / max(lum[bottom].mean(), 1e-9)), 4),
        "contact_bbox_min_z": placement["bbox_min_z"],
        "render": os.path.basename(path),
    }


def main() -> int:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    rci = _load_render_module()

    results = {m: measure(rci, args, m) for m in ("no_ground", "shadow_catcher", "matte_ground", "split")}
    baseline = results["no_ground"]["bottom"]

    violations = []
    for mode in ("shadow_catcher", "matte_ground", "split"):
        bottom = results[mode]["bottom"]
        if bottom > baseline:
            violations.append({
                "mode": mode,
                "bottom_with_ground": bottom,
                "bottom_no_ground": baseline,
                "excess": round(bottom - baseline, 6),
                "why": "a ground plane must not add light to the object's lower hemisphere; "
                       "this one is transmitting the environment's lower hemisphere through "
                       "the surface the object is standing on",
            })

    production_violations = [v for v in violations if v["mode"] in ("matte_ground", "split")]
    expected_known_fail = next((v for v in violations if v["mode"] == "shadow_catcher"), None)
    passed = not production_violations and expected_known_fail is not None
    report = {
        "hdr": os.path.basename(args.hdr),
        "samples": args.samples,
        "invariant": "bottom_luminance(with_ground) <= bottom_luminance(no_ground)",
        "results": results,
        "violations": violations,
        "expected_known_fail": expected_known_fail,
        "production_violations": production_violations,
        "passed": passed,
    }
    json.dump(report, open(os.path.join(args.out_dir, "light_field_regression.json"), "w"), indent=2)
    print("LIGHT_FIELD " + json.dumps(report))
    if not passed:
        print("FAIL: production proxy violated the invariant or legacy known-fail disappeared")
        return 1
    print("PASS: production proxy removes light from below; legacy catcher failure retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
