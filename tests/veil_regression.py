"""Veil regression: does the plate merge leave untouched plate alone?

Run inside Blender:
    blender -b -P tests/veil_regression.py -- --hdr <hdri> --out-dir <dir>

Why this test exists
--------------------
Bert, 2026-08-15 (#latent-merge): *"The on/off cancellation result is strong
enough to move from 'plausible mitigation' to a scoped acceptance test:
identical proxy field in both halves, measure footprint-only residual outside
the object interaction mask, and require the ratio deviation/p99 to stay near
the noise floor. That keeps the fix tied to the actual failure without claiming
the final composite is approved."*

That is the scope. This test asserts one thing — that the ground setup does not
modify plate the object never touched. It says nothing about whether the
resulting composite looks correct.

The defect it guards against
----------------------------
`reports/ground-proxy-production-20260815/` rejected a composite whose ground
setup veiled 35% of frame. `reports/proxy-isolation-20260815/` attributed it:
the Cycles shadow catcher computes its plate merge as a shadowing ratio against
any object that occludes it, and a coincident camera-hidden transport proxy is
such an object, so the proxy's occlusion of the catcher was written into the
plate as a cast shadow across the whole ground plane. Neither component does
this alone. It is a property of the pair, which is why a test on either half
would have passed.

The metric
----------
One question asked of both ground setups: *by what fraction does this setup
change plate the object is not interacting with?*

    production   ground_with_object / ground_alone   - 1
    legacy       (catcher + proxy)  / background     - 1

Different plumbing, same quantity, same region, same threshold.

Why the legacy arm is here
--------------------------
A test that only checks the shipping path cannot show it has teeth. The legacy
arm re-renders the setup rejected on 2026-08-15 and the test fails if that
setup *stops* violating the threshold, exactly as `light_field_regression.py`
retains its known-fail. Without it, this file would pass just as happily if the
metric were broken.

A first version of this test tried to derive the threshold from a null pair —
`ground_alone` rendered twice under different seeds. That was wrong and is
recorded here so it is not retried: the real pair shares a seed, so its sampling
noise is strongly correlated and largely cancels, while a different-seed null is
decorrelated and carries full noise. The null measured 265x *larger* residual
than the pair it was supposed to bound, making the budget vacuous. Two renders
that share a seed are byte-identical, so there is no same-seed null available.
The thresholds are therefore absolute, and the legacy arm is what keeps them
honest.

Why the exclusion zone is geometric
-----------------------------------
The object interaction mask is a radius around the object derived from its own
alpha, not from the ratio being tested. Deriving the mask from the measurement
would let a large enough defect define itself as legitimate interaction and pass.

Exit code 0 = the plate merge is confined to the object's neighbourhood and the
legacy defect still reproduces.
Exit 1 = plate the object never touched is being modified, or the legacy arm
stopped failing and this test no longer proves anything.
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
    print("veil_regression.py must be run inside Blender: blender -b -P ... -- <args>")
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
    p.add_argument("--place-uv", type=float, nargs=2, default=[0.46, 0.86])
    p.add_argument("--cam-height", type=float, default=1.6)
    p.add_argument("--object-height", type=float, default=0.45)
    p.add_argument("--asset", default="ref_balls")
    p.add_argument("--ground-albedo", type=float, default=0.08)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=540)
    p.add_argument("--exclusion-radii", type=float, default=3.0,
                   help="object interaction zone, in multiples of the object's own "
                        "image-space radius; excluded from the assertion")
    # Measured 2026-08-15 at 1920x1080/512spp: the production path sits at
    # 1.4e-04 mean / 2.9e-03 p99 and the rejected legacy setup at ~1e-01 mean.
    # These sit an order of magnitude above production and an order below legacy,
    # so neither arm is near its edge.
    p.add_argument("--max-mean", type=float, default=2e-3)
    p.add_argument("--max-p99", type=float, default=2e-2)
    return p.parse_args(_argv_after_dashes())


def _read(path: str) -> np.ndarray:
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, img.channels)[::-1]
    bpy.data.images.remove(img)
    return px.copy()


def _lum(a: np.ndarray) -> np.ndarray:
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def _emissive_white(name: str):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def _black_world() -> None:
    w = bpy.data.worlds.new("black")
    w.use_nodes = True
    w.node_tree.nodes.clear()
    bg = w.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0, 0, 0, 1)
    out = w.node_tree.nodes.new("ShaderNodeOutputWorld")
    w.node_tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bpy.context.scene.world = w


def build(rci, args, mode: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if mode == "footprint":
        _black_world()
    else:
        rci.setup_world(args.hdr)
    az = rci._plate_yaw_to_blender_azimuth(args.yaw)
    cam = rci.setup_camera(az, args.pitch, args.hfov, (0, 0, args.cam_height))
    bpy.context.view_layer.update()
    hit = rci.ground_hit_from_pixel(cam, *args.place_uv, args.hfov, args.height / args.width)

    if mode == "background":
        return                       # world only; the legacy arm's denominator

    if mode == "legacy_off":
        # The setup rejected on 2026-08-15: Cycles shadow catcher doing the plate
        # merge with a coincident camera-hidden transport proxy beside it.
        rci.add_ground(shadow_catcher=True)
        proxy = rci.add_light_proxy(args.ground_albedo, "ground_light_proxy")
        rci.assert_light_proxy_contract(proxy)
        return

    if mode == "object_only":
        proxy = rci.add_light_proxy(args.ground_albedo, "ground_light_proxy")
        rci.assert_light_proxy_contract(proxy)
    else:
        ground = rci.add_ground(shadow_catcher=False)
        ground.name = "ground_matte"
        mat = (_emissive_white("footprint") if mode == "footprint"
               else rci._matte("ground_matte", args.ground_albedo))
        ground.data.materials.append(mat)

    if mode in ("ground_only", "footprint"):
        return
    obj = rci.build_asset(args.asset, args.object_height)
    if args.asset == "ref_balls":
        rci.orient_across_view(obj, hit)
    rci.rest_on_ground(obj, hit, target_height=args.object_height)


def main() -> int:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    rci = _load_render_module()

    # Every render shares seed 0: the metric is a ratio between two renders, and
    # decorrelating their sampling would measure noise instead of the setup.
    frames = {}
    for mode in ("background", "legacy_off", "ground_only", "ground_object",
                 "object_only", "footprint"):
        build(rci, args, mode)
        path = os.path.join(args.out_dir, f"{mode}.exr")
        rci.render(path, args.width, args.height, args.samples,
                   transparent=(mode == "object_only"),
                   linear=True, denoise=False, seed=0)
        frames[mode] = _read(path)
        print(f"RENDERED {mode}")

    eps = 1e-6
    lums = {k: _lum(v[..., :3]) for k, v in frames.items()}
    production = (lums["ground_object"] + eps) / (lums["ground_only"] + eps)
    legacy = (lums["legacy_off"] + eps) / (lums["background"] + eps)

    footprint = lums["footprint"] > 0.5
    alpha = frames["object_only"][..., 3]
    obj = alpha > 0.5
    if not obj.any():
        raise SystemExit("object did not render; nothing to exclude")

    # Geometric exclusion zone around the object, from the object's own alpha.
    ys, xs = np.nonzero(obj)
    cy, cx = ys.mean(), xs.mean()
    radius = float(np.hypot(ys - cy, xs - cx).max())
    Y, X = np.mgrid[0 : args.height, 0 : args.width]
    interaction_zone = np.hypot(Y - cy, X - cx) <= args.exclusion_radii * radius

    # The assertion region: ground the object provably cannot be interacting with.
    region = footprint & ~interaction_zone & (alpha < 0.01)
    if region.sum() < 1000:
        raise SystemExit(f"assertion region is only {int(region.sum())} px; "
                         "widen the frame or shrink --exclusion-radii")

    def resid(r: np.ndarray) -> dict:
        d = np.abs(r[region] - 1.0)
        return {"mean": float(f"{d.mean():.3e}"), "p99": float(f"{np.percentile(d, 99):.3e}")}

    prod_r, legacy_r = resid(production), resid(legacy)
    budget = {"mean": args.max_mean, "p99": args.max_p99}

    production_violations = [k for k in ("mean", "p99") if prod_r[k] > budget[k]]
    # The legacy arm has to keep failing, or this test proves nothing.
    legacy_reproduces = any(legacy_r[k] > budget[k] for k in ("mean", "p99"))
    passed = not production_violations and legacy_reproduces

    report = {
        "hdr": os.path.basename(args.hdr),
        "asserts": "on footprint outside the object interaction zone, the production "
                   "ground setup changes the plate by less than the budget, while the "
                   "rejected legacy setup still exceeds it",
        "metric": "|ratio - 1| where ratio is the setup's multiplier on untouched plate",
        "resolution": [args.width, args.height],
        "samples": args.samples,
        "denoising": False,
        "exclusion_radii": args.exclusion_radii,
        "object_image_radius_px": round(radius, 1),
        "assertion_region_px": int(region.sum()),
        "assertion_region_fraction": round(float(region.mean()), 4),
        "budget": budget,
        "production_residual": prod_r,
        "legacy_residual": legacy_r,
        "production_violations": production_violations,
        "legacy_reproduces_defect": legacy_reproduces,
        "headroom_x": round(budget["mean"] / max(prod_r["mean"], 1e-12), 1),
        "passed": passed,
    }
    json.dump(report, open(os.path.join(args.out_dir, "veil_regression.json"), "w"), indent=2)
    print("VEIL_REGRESSION " + json.dumps(report))
    if production_violations:
        print(f"FAIL: plate outside the object's interaction zone is being modified "
              f"({production_violations}); this is the 2026-08-15 veil defect or a relative")
        return 1
    if not legacy_reproduces:
        print("FAIL: the legacy catcher+proxy setup no longer exceeds the budget, so this "
              "test has stopped demonstrating that it can detect the defect")
        return 1
    print("PASS: the plate merge is confined to the object's neighbourhood; "
          "the legacy defect still reproduces")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
