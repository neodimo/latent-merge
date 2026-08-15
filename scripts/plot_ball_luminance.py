"""Luminance strips down a reference sphere — make an over-lit underside visible.

    .venv/bin/python scripts/plot_ball_luminance.py \
        --plate <plate_rgb.png> --pair <ref_balls cg_rgba.png> \
        --ball MODE=<ball_MODE.png> [--ball ...] --out <figure.png>

Bert, 2026-08-15 (#latent-merge): *"crop just the balls plus nearby asphalt and
include luminance strips top-to-bottom on the gray ball. It will make the
'underside is over-lit' defect obvious without relying on the full-frame read."*

A single mean number per hemisphere says the underside is too bright; it does not
show *where* the sphere stops behaving. Averaging luminance along each scanline
inside the sphere's own mask gives a profile from crown to contact point, and
plotting several ground modes on the same axes turns the defect into a shape:
a correctly occluded sphere falls away steeply toward the contact point, and one
lit through its own floor flattens out or lifts.

The nearby asphalt is drawn as a reference line because the sphere's underside is
supposed to be reading that surface's bounce, not the environment behind it.
"""
from __future__ import annotations

import argparse

import cv2
import numpy as np

# Drawn in BGR. Shipping path red, proposal green, baseline neutral.
COLORS = {
    "shadow_catcher": (70, 70, 235),
    "split": (110, 210, 110),
    "no_ground": (200, 200, 200),
    "matte_ground": (210, 170, 90),
}


def luminance(bgr: np.ndarray) -> np.ndarray:
    c = bgr.astype(np.float32) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 2] + 0.7152 * c[..., 1] + 0.0722 * c[..., 0]


def scanline_profile(rgba: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean luminance per scanline inside the sphere, plus normalised height.

    Only fully opaque pixels count, so the cast shadow and the antialiased rim
    cannot drag the sphere's own values around.
    """
    mask = rgba[..., 3] > 240
    lum = luminance(rgba[..., :3])
    rows = np.nonzero(mask.any(1))[0]
    y0, y1 = rows.min(), rows.max()
    values = np.array([lum[y][mask[y]].mean() for y in range(y0, y1 + 1)])
    height = np.linspace(0.0, 1.0, len(values))  # 0 = crown, 1 = contact point
    return height, values


def draw_plot(w: int, h: int, series: dict, asphalt: float, title: str) -> np.ndarray:
    fig = np.full((h, w, 3), 24, np.uint8)
    left, right, top, bottom = 96, w - 210, 58, h - 54
    vmax = max(max(v.max() for _, v in series.values()), asphalt) * 1.12

    def px(height: float, value: float) -> tuple[int, int]:
        return (int(left + (right - left) * value / vmax),
                int(top + (bottom - top) * height))

    for frac in np.linspace(0, 1, 5):
        x = int(left + (right - left) * frac)
        cv2.line(fig, (x, top), (x, bottom), (52, 52, 52), 1)
        cv2.putText(fig, f"{frac*vmax:.2f}", (x - 22, bottom + 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (150, 150, 150), 1)
    cv2.rectangle(fig, (left, top), (right, bottom), (90, 90, 90), 1)

    ax = px(0, asphalt)[0]
    cv2.line(fig, (ax, top), (ax, bottom), (110, 200, 235), 1, cv2.LINE_AA)
    cv2.putText(fig, "asphalt", (ax + 6, bottom - 8), cv2.FONT_HERSHEY_SIMPLEX,
                0.44, (110, 200, 235), 1)

    # Shade the light the ground *added* — the defect itself, rather than asking
    # the reader to spot that one curve sits right of another.
    if {"no_ground", "shadow_catcher"} <= set(series):
        base_h, base_v = series["no_ground"]
        bad_h, bad_v = series["shadow_catcher"]
        n = min(len(base_v), len(bad_v))
        band = [px(base_h[i], base_v[i]) for i in range(n)]
        band += [px(bad_h[i], bad_v[i]) for i in range(n - 1, -1, -1)]
        overlay = fig.copy()
        cv2.fillPoly(overlay, [np.array(band, np.int32)], (60, 60, 190))
        cv2.addWeighted(overlay, 0.42, fig, 0.58, 0, fig)

    for label, (height, values) in series.items():
        color = COLORS.get(label, (200, 200, 200))
        pts = np.array([px(hh, vv) for hh, vv in zip(height, values)], np.int32)
        cv2.polylines(fig, [pts], False, color, 2, cv2.LINE_AA)
        cv2.circle(fig, tuple(pts[-1]), 5, color, -1, cv2.LINE_AA)

    # Legend in the empty upper-left of the axes; per-curve end labels collided.
    ly = top + 22
    for label, (_, values) in series.items():
        color = COLORS.get(label, (200, 200, 200))
        cv2.line(fig, (left + 16, ly - 5), (left + 46, ly - 5), color, 3, cv2.LINE_AA)
        cv2.putText(fig, f"{label}  contact {values[-8:].mean():.4f}",
                    (left + 56, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.46, color, 1,
                    cv2.LINE_AA)
        ly += 26
    if {"no_ground", "shadow_catcher"} <= set(series):
        cv2.putText(fig, "shaded = light the ground ADDED (impossible)",
                    (left + 16, ly + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                    (120, 120, 235), 1, cv2.LINE_AA)

    cv2.putText(fig, title, (left, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                (240, 240, 240), 1, cv2.LINE_AA)
    cv2.putText(fig, "crown", (14, top + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                (170, 170, 170), 1)
    cv2.putText(fig, "contact", (14, bottom), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                (170, 170, 170), 1)
    cv2.putText(fig, "luminance ->", (left, h - 16), cv2.FONT_HERSHEY_SIMPLEX,
                0.46, (150, 150, 150), 1)
    return fig


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plate", required=True)
    ap.add_argument("--pair", required=True, help="ref_balls cg_rgba.png")
    ap.add_argument("--ball", action="append", required=True, metavar="MODE=PATH",
                    help="single gray-ball RGBA render per ground mode")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pad", type=int, default=110, help="asphalt margin around the crop")
    args = ap.parse_args()

    plate = cv2.imread(args.plate)
    pair = cv2.imread(args.pair, cv2.IMREAD_UNCHANGED)
    alpha = pair[..., 3:4].astype(np.float32) / 255.0
    comp = (plate.astype(np.float32) * (1 - alpha)
            + pair[..., :3].astype(np.float32) * alpha).astype(np.uint8)

    solid = pair[..., 3] > 240
    ys, xs = np.nonzero(solid)
    y0, y1 = max(0, ys.min() - args.pad), min(comp.shape[0], ys.max() + args.pad)
    x0, x1 = max(0, xs.min() - args.pad), min(comp.shape[1], xs.max() + args.pad)
    crop = comp[y0:y1, x0:x1]

    # Asphalt reference: plate pixels in the crop, excluding anything the insert
    # touched, so it is the surface the underside should be reading.
    touched = (pair[..., 3] > 2)[y0:y1, x0:x1]
    asphalt = float(luminance(plate[y0:y1, x0:x1])[~touched].mean())

    series = {}
    for spec in args.ball:
        mode, _, path = spec.partition("=")
        series[mode] = scanline_profile(cv2.imread(path, cv2.IMREAD_UNCHANGED))

    side = 700
    crop_r = cv2.resize(crop, (int(crop.shape[1] * side / crop.shape[0]), side))
    cv2.rectangle(crop_r, (0, 0), (crop_r.shape[1], 44), (0, 0, 0), -1)
    cv2.putText(crop_r, "18% matte + chrome, shipping path", (12, 31),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    plot = draw_plot(940, side, series, asphalt,
                     "mean luminance per scanline, crown -> contact")
    cv2.imwrite(args.out, np.hstack([crop_r, plot]))

    print("ASPHALT %.4f" % asphalt)
    for mode, (_, values) in series.items():
        print("%-15s crown %.4f  contact %.4f  contact/asphalt %.2f"
              % (mode, values[:8].mean(), values[-8:].mean(),
                 values[-8:].mean() / max(asphalt, 1e-9)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
