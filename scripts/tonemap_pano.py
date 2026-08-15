"""HDR equirect -> LDR equirect through Blender's own view transform.

Run inside Blender:
    blender -b -P scripts/tonemap_pano.py -- --hdr in.hdr --out out.png

Why this exists
---------------
The plate and the CG insert have to end up in the *same* display space or no
amount of relighting can make them agree. Previously the plate was tonemapped
by OpenCV's Reinhard operator while the CG was rendered by Cycles through AgX.
Two different curves applied to the same captured radiance produce two images
that can never match, and the washed-out plates that blocked the intake tranche
were that mismatch showing up as "non-photographic".

So the plate is now tonemapped by the same OCIO view transform Cycles renders
through. `Image.save_render` runs the scene's display/view settings over the
float buffer, which is exactly the operator applied to a render. Plate pixels
and CG pixels are then in one display space by construction rather than by
coincidence, and the raw (not contrast-normalised) plate-vs-render comparison
becomes a meaningful check.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import bpy
except ImportError:  # pragma: no cover - only importable inside Blender
    print("tonemap_pano.py must be run inside Blender: blender -b -P ... -- <args>")
    raise SystemExit(2)


def _argv_after_dashes() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hdr", required=True, help="equirectangular HDR/EXR input")
    p.add_argument("--out", required=True, help="LDR PNG output")
    p.add_argument("--view-transform", default="AgX",
                   help="OCIO view transform; must match the render (default AgX)")
    p.add_argument("--look", default="None", help="OCIO look, e.g. 'AgX - Punchy'")
    p.add_argument("--exposure", type=float, default=0.0, help="stops")
    p.add_argument("--gamma", type=float, default=1.0)
    p.add_argument("--meta", help="optional path for a JSON record of the transform")
    return p.parse_args(_argv_after_dashes())


def apply_view_settings(view_transform: str, look: str, exposure: float, gamma: float) -> dict:
    """Set colour management and fail loudly if the requested transform is absent.

    A silently ignored view transform would reintroduce exactly the mismatch
    this script exists to remove, so an unavailable name is an error.
    """
    scn = bpy.context.scene
    scn.display_settings.display_device = "sRGB"
    vs = scn.view_settings
    try:
        vs.view_transform = view_transform
    except TypeError as exc:
        raise SystemExit(f"view transform {view_transform!r} not in this OCIO config: {exc}")
    try:
        vs.look = look
    except TypeError:
        vs.look = "None"
    vs.exposure = exposure
    vs.gamma = gamma
    return {
        "view_transform": vs.view_transform,
        "look": vs.look,
        "exposure": vs.exposure,
        "gamma": vs.gamma,
        "display_device": scn.display_settings.display_device,
    }


def main() -> int:
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    settings = apply_view_settings(args.view_transform, args.look, args.exposure, args.gamma)

    img = bpy.data.images.load(args.hdr)
    # The HDR must be read as scene-linear radiance; if it were interpreted as
    # sRGB the view transform would be applied on top of an already-encoded
    # image and the result would be doubly gamma'd.
    img.colorspace_settings.name = "Linear Rec.709"
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    scn = bpy.context.scene
    scn.render.image_settings.file_format = "PNG"
    scn.render.image_settings.color_mode = "RGB"
    scn.render.image_settings.color_depth = "8"
    img.save_render(filepath=args.out, scene=scn)

    record = dict(settings, source=os.path.basename(args.hdr),
                  size=[img.size[0], img.size[1]], output=os.path.basename(args.out))
    bpy.data.images.remove(img)
    if args.meta:
        json.dump(record, open(args.meta, "w"), indent=2)
    print("TONEMAP " + json.dumps(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
