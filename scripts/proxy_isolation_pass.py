"""Object-on/off isolation pass: is the veil the object's interaction, or the plate path?

Run inside Blender:
    blender -b -P scripts/proxy_isolation_pass.py -- --hdr <hdri> --plate <png> --out-dir <dir>

Why this test exists
--------------------
`reports/ground-proxy-production-20260815/` rejected the first production
composite on pixels: the split ground setup fixed the object's light field but
painted a large veil across road and wall, far bigger than any shadow a 1.1 m
sphere can cast.

Bert, 2026-08-15 (#latent-merge): *"that veil means the proxy is still leaking
into the plate/composite path as an image-space contribution instead of staying
purely in transport. Object-on/off with identical proxies in both halves is the
right isolation pass: if the polygon survives, it's proxy/plate handling; if it
cancels, it's object interaction. I'd also keep the proxy alpha/visibility AOV
beside it so we can see whether the veil is literally the hidden mesh footprint
or a downstream mask/math artifact."*

The design
----------
Six renders, one scene construction, everything else pinned — same camera, same
seed, same sample count, denoiser off, linear EXR:

    bg             world only. No ground, no proxy, no object.
    catcher_only   Cycles shadow catcher alone, object absent.
    proxy_only     camera-hidden matte proxy alone, object absent.
    proxy_off      the full production ground setup (both), object absent.
    proxy_on       the same setup with the object added.
    footprint      the proxy planes made camera-visible and emissive against a
                   black world; the AOV Bert asked for. This is the hidden
                   mesh's literal image-space footprint.

The object-absent renders are all differenced against `bg`, which is the only
honest definition of "what did the ground setup do to plate it was never
supposed to touch":

    veil            = proxy_off    - bg
    veil_catcher    = catcher_only - bg
    veil_proxy      = proxy_only   - bg
    interaction     = proxy_on     - proxy_off

`interaction` is the only quantity entitled to modify the plate. Everything in
a `veil` is a leak, and splitting the setup in half says which half leaks:
a veil that appears only when catcher and proxy are combined is not either
component misbehaving on its own, it is the shadow catcher measuring occlusion
against geometry the pipeline believes is purely a transport helper.

`footprint` then separates two very different causes for the same picture. Veil
energy inside the footprint means a hidden mesh is accounted for in the plate
merge. Veil energy outside it has no mesh under it at all and is a downstream
mask or math artifact.

Exit code 0 = the isolation ran and its verdict is written. This is an
instrument; it does not assert a pass/fail on the pipeline, it attributes the
defect to a layer. The attribution is in `verdict` in the JSON.
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
    print("proxy_isolation_pass.py must be run inside Blender: blender -b -P ... -- <args>")
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
    p.add_argument("--yaw", type=float, default=None,
                   help="plate yaw; read from the extraction manifest beside --plate when omitted")
    p.add_argument("--pitch", type=float, default=-6.0)
    p.add_argument("--hfov", type=float, default=72.0)
    p.add_argument("--place-uv", type=float, nargs=2, default=[0.42, 0.88])
    p.add_argument("--cam-height", type=float, default=1.6)
    p.add_argument("--object-height", type=float, default=1.1)
    p.add_argument("--asset", default="ref_balls")
    p.add_argument("--ground-albedo", type=float, default=0.08)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=540)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--view-transform", default="AgX")
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


def _read_linear(path: str) -> np.ndarray:
    """Read a float EXR back as scene-referred RGB, top row first."""
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, img.channels)[::-1]
    bpy.data.images.remove(img)
    return px[..., :3].copy()


def _lum(a: np.ndarray) -> np.ndarray:
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def _emissive_white(name: str) -> "bpy.types.Material":
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def _black_world() -> None:
    scn = bpy.context.scene
    scn.world = bpy.data.worlds.new("black")
    scn.world.use_nodes = True
    nt = scn.world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0, 0, 0, 1)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])


def build(rci, args, mode: str) -> dict:
    """Construct one half of the pair. Camera and world are identical in all
    modes; only the ground setup and the object's presence vary."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if mode == "footprint":
        _black_world()
    else:
        rci.setup_world(args.hdr)
    az = rci._plate_yaw_to_blender_azimuth(args.yaw)
    cam = rci.setup_camera(az, args.pitch, args.hfov, (0, 0, args.cam_height))
    bpy.context.view_layer.update()
    u, v = args.place_uv
    hit = rci.ground_hit_from_pixel(cam, u, v, args.hfov, args.height / args.width)

    info: dict = {"mode": mode, "azimuth_deg": az}

    if mode == "bg":
        return info

    if mode == "footprint":
        # The AOV: exactly the geometry that is supposed to be invisible to the
        # camera, forced visible and emissive. Its footprint is what the veil
        # gets compared against.
        catcher = rci.add_ground(shadow_catcher=True)
        catcher.is_shadow_catcher = False
        catcher.data.materials.append(_emissive_white("footprint_catcher"))
        proxy = rci.add_light_proxy(args.ground_albedo, "ground_light_proxy")
        proxy.data.materials.clear()
        proxy.data.materials.append(_emissive_white("footprint_proxy"))
        proxy.visible_camera = True
        return info

    # The rejected production setup, reproduced exactly: Cycles shadow catcher
    # for the plate merge plus a coincident camera-hidden matte proxy carrying
    # the light transport. `catcher_only` and `proxy_only` are the same setup
    # with one half removed, so a veil can be attributed to a component or to
    # their interaction.
    if mode in ("catcher_only", "proxy_off", "proxy_on"):
        rci.add_ground(shadow_catcher=True)
    if mode in ("proxy_only", "proxy_off", "proxy_on"):
        proxy = rci.add_light_proxy(args.ground_albedo, "ground_light_proxy")
        rci.assert_light_proxy_contract(proxy)
        info["proxy_visibility"] = {
            "visible_camera": proxy.visible_camera,
            "visible_shadow": proxy.visible_shadow,
            "visible_diffuse": proxy.visible_diffuse,
            "visible_glossy": proxy.visible_glossy,
        }

    if mode != "proxy_on":
        return info

    obj = rci.build_asset(args.asset, args.object_height)
    info["placement"] = rci.rest_on_ground(obj, hit, target_height=args.object_height)
    return info


def render_mode(rci, args, mode: str) -> tuple[np.ndarray, dict]:
    info = build(rci, args, mode)
    path = os.path.join(args.out_dir, f"{mode}.exr")
    # Opaque film: every mode must produce a full frame including background,
    # or the difference between two of them is not defined outside the object.
    rci.render(path, args.width, args.height, args.samples, transparent=False,
               linear=True, denoise=False, seed=args.seed)
    info["render"] = os.path.basename(path)
    return _read_linear(path), info


def _region_stats(delta_lum: np.ndarray, mask: np.ndarray) -> dict:
    if not mask.any():
        return {"pixels": 0}
    d = delta_lum[mask]
    return {
        "pixels": int(mask.sum()),
        "mean_abs": round(float(np.abs(d).mean()), 6),
        "p99_abs": round(float(np.percentile(np.abs(d), 99)), 6),
        "max_abs": round(float(np.abs(d).max()), 6),
    }


def main() -> int:
    args = parse_args()
    args.yaw = _yaw_beside_plate(args.plate, args.yaw)
    os.makedirs(args.out_dir, exist_ok=True)
    rci = _load_render_module()
    rci.VIEW.update(view_transform=args.view_transform, look="None", exposure=0.0, gamma=1.0)

    modes = ("bg", "catcher_only", "proxy_only", "proxy_off", "proxy_on", "footprint")
    frames: dict[str, np.ndarray] = {}
    infos: dict[str, dict] = {}
    for mode in modes:
        frames[mode], infos[mode] = render_mode(rci, args, mode)
        print(f"RENDERED {mode}")

    veils = {
        "production": frames["proxy_off"] - frames["bg"],
        "catcher_only": frames["catcher_only"] - frames["bg"],
        "proxy_only": frames["proxy_only"] - frames["bg"],
    }
    veil_lum = {k: _lum(v) for k, v in veils.items()}
    inter_lum = _lum(frames["proxy_on"] - frames["proxy_off"])

    # The proxy's literal image-space footprint. Emissive white against a black
    # world, so any pixel with real energy is covered geometry.
    footprint = _lum(frames["footprint"]) > 0.5
    outside = ~footprint

    # Where the object itself lives, taken from the interaction image: the
    # object's own pixels are a legitimate large change and must not be counted
    # as veil or as its own shadow.
    obj_mask = np.abs(inter_lum) > 0.05
    plate_only = outside | (footprint & ~obj_mask)

    # A noise floor for this sample count, measured rather than assumed: the
    # top eighth of frame is sky in this plate and contains no ground, no proxy
    # and no object, so whatever difference appears there is sampling noise.
    # Floored at 1e-3 because a shared seed can make that region cancel to
    # exactly zero, and a zero threshold would call one stray pixel a defect.
    sky = np.zeros_like(footprint)
    sky[: max(args.height // 8, 1)] = True
    sky &= ~footprint & ~obj_mask
    measured_floor = float(np.percentile(np.abs(veil_lum["production"][sky]), 99)) if sky.any() else 0.0
    threshold = max(4 * measured_floor, 1e-3)

    stats: dict = {
        "noise_floor_p99": round(measured_floor, 6),
        "hot_threshold": round(threshold, 6),
        "interaction_in_footprint": _region_stats(inter_lum, footprint & ~obj_mask),
        "interaction_outside_footprint": _region_stats(inter_lum, outside),
    }
    for name, lum in veil_lum.items():
        stats[f"veil_{name}_in_footprint"] = _region_stats(lum, footprint & ~obj_mask)
        stats[f"veil_{name}_outside_footprint"] = _region_stats(lum, outside)

    def hot(key: str) -> bool:
        return stats[key].get("p99_abs", 0.0) > threshold

    inside_hot = hot("veil_production_in_footprint")
    outside_hot = hot("veil_production_outside_footprint")
    catcher_hot = hot("veil_catcher_only_in_footprint")
    proxy_hot = hot("veil_proxy_only_in_footprint")

    if not inside_hot and not outside_hot:
        verdict = ("no veil: the ground setup leaves untouched plate alone at this "
                   "sample count, so the rejected polygon was the object's own "
                   "interaction and the defect is in the object layer, not the plate path")
    elif outside_hot and not inside_hot:
        verdict = ("downstream mask or math artifact: the veil sits outside the proxy "
                   "footprint entirely, so no hidden mesh explains it")
    elif inside_hot and not catcher_hot and not proxy_hot:
        verdict = ("component interaction in the plate merge: neither the shadow catcher "
                   "nor the hidden proxy veils the plate alone, but together they do. "
                   "The catcher is measuring occlusion against geometry the pipeline "
                   "treats as a transport-only helper, so the proxy's shading of the "
                   "catcher is being written into the plate as if it were a shadow")
    elif inside_hot and proxy_hot and not catcher_hot:
        verdict = ("proxy handling: the hidden proxy veils the plate on its own, so it "
                   "is reaching the camera path despite its declared visibility contract")
    elif inside_hot and catcher_hot:
        verdict = ("shadow-catcher handling: the catcher veils untouched plate with no "
                   "proxy present at all, so the plate merge is wrong before the proxy "
                   "is even involved")
    else:
        verdict = ("mixed: veil energy both inside and outside the proxy footprint; "
                   "the footprint does not explain it on its own")

    # Does the fix the isolation implies actually work on this data? A veil that
    # is identical in both halves must cancel out of the ratio proxy_on/proxy_off,
    # which is what a difference-based composite multiplies the plate by. Checked
    # here rather than asserted, over the footprint pixels the object provably
    # does not touch.
    lum_on, lum_off, lum_bg = _lum(frames["proxy_on"]), _lum(frames["proxy_off"]), _lum(frames["bg"])
    untouched = footprint & ~obj_mask & (np.abs(inter_lum) < 1e-4)
    ratio = (lum_on + 1e-6) / (lum_off + 1e-6)
    dev = np.abs(ratio[untouched] - 1.0)
    additive = float(np.abs(lum_off - lum_bg)[untouched].mean())
    cancellation = {
        "pixels": int(untouched.sum()),
        "additive_veil_mean_abs": round(additive, 6),
        "ratio_deviation_from_one_mean": float(f"{dev.mean():.3e}"),
        "ratio_deviation_from_one_p99": float(f"{np.percentile(dev, 99):.3e}"),
        "suppression_factor": round(additive / max(float(dev.mean()), 1e-12), 1),
        "note": "the veil is common to both halves, so a ratio composite removes it "
                "by construction; this is the measurement of that, not a claim about it",
    }

    report = {
        "hdr": os.path.basename(args.hdr),
        "plate": os.path.basename(args.plate),
        "yaw_deg": args.yaw,
        "pitch_deg": args.pitch,
        "hfov_deg": args.hfov,
        "samples": args.samples,
        "seed": args.seed,
        "resolution": [args.width, args.height],
        "denoising": False,
        "modes": infos,
        "footprint_coverage": round(float(footprint.mean()), 4),
        "object_coverage": round(float(obj_mask.mean()), 4),
        "plate_only_coverage": round(float(plate_only.mean()), 4),
        "stats": stats,
        "ratio_cancellation": cancellation,
        "verdict": verdict,
    }
    json.dump(report, open(os.path.join(args.out_dir, "proxy_isolation.json"), "w"), indent=2)
    print("PROXY_ISOLATION " + json.dumps(report))
    print("VERDICT " + verdict)

    for name, lum in veil_lum.items():
        np.save(os.path.join(args.out_dir, f"veil_{name}_lum.npy"), lum)
    np.save(os.path.join(args.out_dir, "interaction_lum.npy"), inter_lum)
    np.save(os.path.join(args.out_dir, "footprint.npy"), footprint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
