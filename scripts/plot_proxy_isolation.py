"""Evidence sheet for the object-on/off isolation pass.

    .venv/bin/python scripts/plot_proxy_isolation.py \
        --iso-dir <proxy_isolation_pass out-dir> --out <figure.png>

The isolation pass produces four difference images that only mean something
against each other, so they are drawn on **one shared amplification scale**.
Three of them are what the ground setup does to plate it should never touch,
and the fourth is the object's actual contribution. Putting them on separate
auto-scaled colour maps would make a 13x difference in magnitude look identical,
which is exactly the mistake this figure exists to prevent.

Signed difference is drawn blue where the setup darkened the plate and red where
it brightened it, because the direction is diagnostic: a legitimate contact
shadow can only ever darken.
"""
from __future__ import annotations

import argparse
import json
import os

import cv2
import numpy as np

# Panels are laid out in reading order and share one scale bar.
PANELS = [
    ("veil_production_lum.npy", "VEIL: catcher + proxy, no object",
     "must be zero everywhere - the object is not in this frame"),
    ("veil_catcher_only_lum.npy", "veil: shadow catcher alone",
     "the plate merge on its own"),
    ("veil_proxy_only_lum.npy", "veil: hidden proxy alone",
     "the transport helper on its own"),
    ("interaction_lum.npy", "INTERACTION: what the object adds",
     "the only thing entitled to modify the plate"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iso-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--gain", type=float, default=None,
                   help="amplification for the difference panels; derived from the "
                        "production veil's 99th percentile when omitted")
    p.add_argument("--panel-width", type=int, default=760)
    return p.parse_args()


def _tonemap(exr: str) -> np.ndarray:
    """A plain Reinhard + sRGB view of a linear EXR, for context panels only.

    Deliberately not the pipeline's AgX transform: this is a reference image to
    look at, and reusing the shipping view transform here would invite reading
    tone off a figure that was never colour-managed for it.
    """
    img = cv2.imread(exr, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"could not read {exr}; set OPENCV_IO_ENABLE_OPENEXR=1")
    rgb = img[..., :3]
    rgb = rgb / (1.0 + rgb)
    return (np.clip(rgb, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


def _signed_map(d: np.ndarray, gain: float) -> np.ndarray:
    """Blue where the plate was darkened, red where it was brightened.

    Zero maps to a mid grey, not to black. Two of these panels are supposed to
    come out flat, and a near-black flat panel reads as a broken figure rather
    than as the measurement it is.
    """
    x = np.clip(d * gain, -1, 1)
    out = np.zeros(d.shape + (3,), dtype=np.float32)
    out[..., 0] = np.clip(-x, 0, 1)   # B: darkened
    out[..., 2] = np.clip(x, 0, 1)    # R: brightened
    grey = 0.42 * (1 - np.abs(x))
    return ((out + grey[..., None]) * 255).clip(0, 255).astype(np.uint8)


def _label(img: np.ndarray, title: str, sub: str, stat: str) -> np.ndarray:
    bar = np.full((74, img.shape[1], 3), 22, dtype=np.uint8)
    cv2.putText(bar, title, (14, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (245, 245, 245), 1, cv2.LINE_AA)
    cv2.putText(bar, sub, (14, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (165, 165, 165), 1, cv2.LINE_AA)
    cv2.putText(bar, stat, (14, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (140, 210, 255), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def main() -> int:
    args = parse_args()
    report = json.load(open(os.path.join(args.iso_dir, "proxy_isolation.json")))
    stats = report["stats"]
    footprint = np.load(os.path.join(args.iso_dir, "footprint.npy"))

    prod = np.load(os.path.join(args.iso_dir, "veil_production_lum.npy"))
    gain = args.gain or 1.0 / max(float(np.percentile(np.abs(prod[footprint]), 99)), 1e-6)

    def scaled(img: np.ndarray) -> np.ndarray:
        h = int(round(args.panel_width * img.shape[0] / img.shape[1]))
        return cv2.resize(img, (args.panel_width, h), interpolation=cv2.INTER_AREA)

    # Footprint outline drawn onto every difference panel: without it there is
    # no way to tell "inside the hidden mesh" from "outside" by eye.
    edges = cv2.Canny((footprint * 255).astype(np.uint8), 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))

    tiles = []
    context = scaled(_tonemap(os.path.join(args.iso_dir, "proxy_on.exr")))
    tiles.append(_label(context, "render: catcher + proxy + object",
                        "the setup rejected on 2026-08-15",
                        f"footprint covers {report['footprint_coverage']:.0%} of frame"))

    fp_vis = scaled(np.dstack([(footprint * 255).astype(np.uint8)] * 3))
    tiles.append(_label(fp_vis, "AOV: hidden proxy footprint",
                        "the mesh declared invisible to camera",
                        "proxy visible_camera = False (asserted)"))

    key = {
        "veil_production_lum.npy": "veil_production_in_footprint",
        "veil_catcher_only_lum.npy": "veil_catcher_only_in_footprint",
        "veil_proxy_only_lum.npy": "veil_proxy_only_in_footprint",
        "interaction_lum.npy": "interaction_in_footprint",
    }
    for name, title, sub in PANELS:
        d = np.load(os.path.join(args.iso_dir, name))
        panel = _signed_map(d, gain)
        panel[edges > 0] = (90, 230, 90)
        s = stats[key[name]]
        tiles.append(_label(scaled(panel), title, sub,
                            f"in footprint: mean |dL| {s['mean_abs']:.5f}  p99 {s['p99_abs']:.5f}"))

    cols = 3
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    width = max(r.shape[1] for r in rows)
    rows = [np.pad(r, ((0, 0), (0, width - r.shape[1]), (0, 0))) for r in rows]
    sheet = np.vstack(rows)

    header = np.full((96, sheet.shape[1], 3), 14, dtype=np.uint8)
    cv2.putText(header, "Object-on/off isolation: the veil is not the object",
                (18, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(header, f"{report['plate']} / {report['hdr']}  -  "
                        f"{report['resolution'][0]}x{report['resolution'][1]}, "
                        f"{report['samples']} spp, seed {report['seed']}, denoiser off, linear EXR  -  "
                        f"all difference panels share one gain ({gain:.0f}x)",
                (18, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (170, 170, 170), 1, cv2.LINE_AA)
    cv2.putText(header, "blue = plate darkened   red = plate brightened   green outline = proxy footprint",
                (18, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (140, 210, 255), 1, cv2.LINE_AA)

    cv2.imwrite(args.out, np.vstack([header, sheet]))
    print(f"WROTE {args.out} gain={gain:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
