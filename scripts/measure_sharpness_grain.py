"""Measure the two things that make a clean composite still read as pasted-on.

    OPENCV_IO_ENABLE_OPENEXR=1 .venv/bin/python scripts/measure_sharpness_grain.py \
        --plate <plate_rgb.png> --composite <composite.png> \
        --object-exr <object_only.exr> --out-dir <dir>

Why this exists
---------------
Bert, 2026-08-15 (#latent-merge): *"keep catcher-only as shipping, keep
difference as an experimental mode/report target, and make the sharpness/grain
mismatch measurable enough that rebasing known-fail 9 means 'better final
composite,' not just 'veil canceled.'"*

`reports/difference-composite-20260815/` closed the veil defect and then said
the spheres still read as razor sharp against a visibly defocused patch of road,
with no grain. That was an eye judgement with no number attached, so it could not
gate anything. This turns it into two numbers.

The two quantities
------------------
**Acutance** — the blur width of an edge in pixels, from an error-function fit to
its intensity profile. A lens defocuses the plate by a real amount at a real
depth; a pinhole CG render does not. Comparing edge *width* works across
different image content, which raw spectra do not: the object and the road are
not pictures of the same thing, so their power spectra differ for reasons that
have nothing to do with focus.

Two earlier versions of this measurement were wrong, and both are recorded so
they are not retried:

1. **10-90% rise distance.** Needs a clean step, and a sphere's limb shading
   keeps changing for tens of pixels past its own silhouette, so any window wide
   enough to hold the transition also holds the shading and the crossings
   measure the shading. Reported an 11 px "edge" on a silhouette antialiased
   over about one pixel.
2. **Second moment of the line spread function.** The textbook route, and it
   failed `--self-test`: given a known 0.8 px blur it recovered 0.53 px. With a
   dozen samples, noise in the far tails is weighted by distance squared and
   drags the width toward the window size — which is why plate and CG both
   measured ~2.4 px no matter what they actually were.

Fitting a model uses the shape of the transition and ignores the tails. Run
`--self-test` before quoting any number from this file: it blurs the plate by
known sigmas and checks the instrument recovers them. It currently recovers with
a systematic under-read of roughly 15-20%, so differences are trustworthy and
absolute values are slightly conservative.

**Grain** — the standard deviation of the high-frequency residual inside flat
regions. Sensor noise lives in the plate and a converged path trace has almost
none, so a CG insert sits in a hole in the noise field. Flat regions are chosen
from a *blurred* copy so the selection is not made by the noise being measured.

Both are reported as plate-versus-CG pairs plus the correction implied, which is
what a later matching pass would apply and what a gate would check afterwards.

This measures. It does not correct anything.
"""
from __future__ import annotations

import argparse
import json
import math
import os

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plate", required=True)
    p.add_argument("--composite")
    p.add_argument("--self-test", action="store_true",
                   help="recover known blur from synthetic data and exit; validates "
                        "the instrument before any real number is quoted")
    p.add_argument("--object-exr",
                   help="RGBA render of the object alone; its alpha locates the insert")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--profile-radius", type=int, default=6,
                   help="half-length in px of the sampled edge profile")
    p.add_argument("--min-contrast", type=float, default=0.06,
                   help="reject edges whose profile contrast is below this, where "
                        "noise dominates the line spread function")
    p.add_argument("--depth-band", type=int, default=160,
                   help="plate edges are only sampled within this many rows of the "
                        "object, so they sit at a comparable depth and defocus")
    p.add_argument("--max-edges", type=int, default=4000)
    return p.parse_args()


def _lum(bgr: np.ndarray) -> np.ndarray:
    return (0.0722 * bgr[..., 0] + 0.7152 * bgr[..., 1] + 0.2126 * bgr[..., 2]).astype(np.float32)


def edge_sigma(lum: np.ndarray, points: np.ndarray, gx: np.ndarray, gy: np.ndarray,
               radius: int, min_contrast: float) -> tuple[np.ndarray, np.ndarray]:
    """Edge blur width in px, sampled along each edge's own gradient normal.

    Returns the per-edge sigmas and the mean normalised edge profile, which is
    the thing worth drawing: a number can be argued with, a profile shape cannot.
    """
    h, w = lum.shape
    if not len(points):
        return np.array([]), np.zeros(2 * radius + 1, np.float32)
    ts = np.arange(-radius, radius + 1, dtype=np.float32)
    y = points[:, 0].astype(np.float32)
    x = points[:, 1].astype(np.float32)
    nx = gx[points[:, 0], points[:, 1]].astype(np.float32)
    ny = gy[points[:, 0], points[:, 1]].astype(np.float32)
    n = np.hypot(nx, ny)
    keep = n > 1e-6
    if not keep.any():
        return np.array([]), np.zeros(2 * radius + 1, np.float32)
    x, y, nx, ny = x[keep], y[keep], nx[keep] / n[keep], ny[keep] / n[keep]

    # One remap for every profile at once; the per-point loop was both slow and
    # the source of a float64 map that cv2.remap rejects.
    sx = np.ascontiguousarray((x[:, None] + ts[None, :] * nx[:, None]).astype(np.float32))
    sy = np.ascontiguousarray((y[:, None] + ts[None, :] * ny[:, None]).astype(np.float32))
    np.clip(sx, 0, w - 1, out=sx)
    np.clip(sy, 0, h - 1, out=sy)
    prof = cv2.remap(lum, sx, sy, cv2.INTER_LINEAR)

    lo = prof.min(axis=1, keepdims=True)
    hi = prof.max(axis=1, keepdims=True)
    contrast = (hi - lo).ravel()
    ok = contrast >= min_contrast
    if not ok.any():
        return np.array([]), np.zeros(2 * radius + 1, np.float32)
    norm = (prof[ok] - lo[ok]) / (hi[ok] - lo[ok])
    # Orient every profile the same way so they can be averaged.
    flip = norm[:, 0] > norm[:, -1]
    norm[flip] = norm[flip][:, ::-1]

    # Keep only profiles that are actually step-shaped: flat on both flanks with
    # the transition in between. Without this the sample is dominated by ramps —
    # a sphere's limb shading, or a gradual tonal change in the plate — whose
    # line spread fills the whole window and reports a blur that is really just
    # the width of the window. That is what made a 1 px CG silhouette measure as
    # 2.4 px, identical to the plate, in the first version of this instrument.
    n_flank = max(radius // 3, 2)
    left, right = norm[:, :n_flank], norm[:, -n_flank:]
    flat_flanks = (left.std(axis=1) < 0.12) & (right.std(axis=1) < 0.12)
    step_like = flat_flanks & (np.abs(norm[:, -n_flank:].mean(axis=1) -
                                      norm[:, :n_flank].mean(axis=1)) > 0.6)
    if not step_like.any():
        return np.array([]), np.zeros(2 * radius + 1, np.float32)
    norm = norm[step_like]

    # Fit an error function to each profile rather than taking the second moment
    # of its derivative. The moment is the textbook route and it failed the
    # self-test here, under-recovering a known 0.8 px blur as 0.53 px: with only
    # a dozen samples, noise in the far tails is weighted by distance squared and
    # inflates the width toward the window size, which is why plate and CG both
    # measured ~2.4 px regardless of what they actually were. Fitting a model
    # uses the shape of the transition and ignores the tails.
    sig_grid = np.linspace(0.25, float(radius), 48)
    mu_grid = np.linspace(-1.5, 1.5, 13) + (norm.shape[1] - 1) / 2.0
    t = np.arange(norm.shape[1], dtype=np.float64)
    erf = np.vectorize(math.erf)
    templates = np.stack([
        0.5 * (1.0 + erf((t - mu) / (s * math.sqrt(2.0))))
        for s in sig_grid for mu in mu_grid
    ])                                            # (n_templates, n_samples)
    sig_of = np.repeat(sig_grid, len(mu_grid))
    # SSE for every profile against every template, expanded so the whole thing
    # is three matrix products instead of a Python loop over profiles.
    sse = (np.square(norm).sum(axis=1)[:, None]
           - 2.0 * norm @ templates.T
           + np.square(templates).sum(axis=1)[None, :])
    best = sse.argmin(axis=1)
    sigma = sig_of[best]
    resid = sse[np.arange(len(best)), best] / norm.shape[1]

    # Drop profiles the model does not describe, and those that pinned to the
    # ends of the grid where the fit is only saying "outside my range".
    good = (resid < 0.01) & (sigma > sig_grid[0] + 1e-9) & (sigma < sig_grid[-1] - 1e-9)
    if not good.any():
        return np.array([]), np.zeros(2 * radius + 1, np.float32)
    return sigma[good], norm[good].mean(axis=0)


def grain_std(lum: np.ndarray, mask: np.ndarray, flat_percentile: float = 40.0) -> dict:
    """High-frequency residual std inside the flattest part of `mask`.

    Flatness is judged on a blurred copy so the noise being measured does not
    decide which pixels get measured.
    """
    blurred = cv2.GaussianBlur(lum, (0, 0), 2.0)
    high = lum - blurred
    structure = cv2.GaussianBlur(np.abs(cv2.Laplacian(blurred, cv2.CV_32F)), (0, 0), 3.0)
    if mask.sum() < 200:
        return {"pixels": int(mask.sum())}
    cut = np.percentile(structure[mask], flat_percentile)
    flat = mask & (structure <= cut)
    if flat.sum() < 100:
        flat = mask
    return {
        "pixels": int(flat.sum()),
        "std": round(float(high[flat].std()), 6),
        "mean_abs": round(float(np.abs(high[flat]).mean()), 6),
    }


def self_test(args) -> int:
    """Recover known blur from synthetic data before trusting the instrument.

    An edge-width measurement that has never been shown to recover a blur it was
    given is not a measurement, it is a number. This blurs the plate by known
    sigmas and checks that the measured width grows in the quadrature the model
    assumes. Failing this means the numbers in the report mean nothing.
    """
    plate = cv2.imread(args.plate).astype(np.float32) / 255.0
    lp = _lum(plate)
    h, w = lp.shape

    def measure(img: np.ndarray) -> float:
        g = cv2.GaussianBlur(img, (0, 0), 1.0)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        mag = np.hypot(gx, gy)
        region = np.zeros_like(img, bool)
        region[h // 3: 2 * h // 3] = True
        strong = region & (mag > np.percentile(mag[region], 99.5))
        pts = np.argwhere(strong)
        if len(pts) > args.max_edges:
            pts = pts[np.linspace(0, len(pts) - 1, args.max_edges).astype(int)]
        s, _ = edge_sigma(img, pts, gx, gy, args.profile_radius, args.min_contrast)
        return float(np.median(s)) if len(s) else float("nan")

    base = measure(lp)
    rows, ok = [], True
    for applied in (0.8, 1.5, 2.5):
        got = measure(cv2.GaussianBlur(lp, (0, 0), applied))
        predicted = float(np.sqrt(base ** 2 + applied ** 2))
        recovered = float(np.sqrt(max(got ** 2 - base ** 2, 0.0)))
        err = abs(recovered - applied) / applied
        rows.append({"applied_sigma": applied, "measured_sigma": round(got, 3),
                     "predicted_sigma": round(predicted, 3),
                     "recovered_sigma": round(recovered, 3),
                     "relative_error": round(err, 3)})
        ok &= err < 0.25
    result = {"baseline_sigma_px": round(base, 3), "trials": rows,
              "passed": bool(ok),
              "criterion": "recovered blur within 25% of applied, for every trial"}
    json.dump(result, open(os.path.join(args.out_dir, "self_test.json"), "w"), indent=2)
    print("SELF_TEST " + json.dumps(result, indent=2))
    return 0 if ok else 1


def main() -> int:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    if args.self_test:
        return self_test(args)

    if not args.composite or not args.object_exr:
        raise SystemExit("--composite and --object-exr are required unless --self-test")
    plate = cv2.imread(args.plate).astype(np.float32) / 255.0
    comp = cv2.imread(args.composite).astype(np.float32) / 255.0
    obj = cv2.imread(args.object_exr, cv2.IMREAD_UNCHANGED)
    if obj is None or obj.shape[2] < 4:
        raise SystemExit(f"{args.object_exr} must be RGBA; set OPENCV_IO_ENABLE_OPENEXR=1")
    alpha = obj[..., 3].astype(np.float32)
    if plate.shape[:2] != comp.shape[:2] or plate.shape[:2] != alpha.shape:
        raise SystemExit("plate, composite and object alpha must share a resolution")

    lp, lc = _lum(plate), _lum(comp)
    inside = alpha > 0.9
    if not inside.any():
        raise SystemExit("object alpha is empty")
    ys, xs = np.nonzero(inside)
    y0, y1 = ys.min(), ys.max()

    # --- CG edges: the object's own silhouette in the composite -------------
    edge_band = (cv2.dilate((alpha > 0.5).astype(np.uint8), np.ones((5, 5), np.uint8)) -
                 cv2.erode((alpha > 0.5).astype(np.uint8), np.ones((5, 5), np.uint8))) > 0
    ag = cv2.GaussianBlur(alpha, (0, 0), 1.0)
    agx = cv2.Sobel(ag, cv2.CV_32F, 1, 0, ksize=3)
    agy = cv2.Sobel(ag, cv2.CV_32F, 0, 1, ksize=3)
    cg_pts = np.argwhere(edge_band)
    if len(cg_pts) > args.max_edges:
        cg_pts = cg_pts[np.linspace(0, len(cg_pts) - 1, args.max_edges).astype(int)]
    cg_sigma, cg_prof = edge_sigma(lc, cg_pts, agx, agy, args.profile_radius, args.min_contrast)

    # --- Plate edges: real detail at a comparable depth, object excluded -----
    band = np.zeros_like(inside)
    band[max(y0 - args.depth_band, 0): min(y1 + args.depth_band, band.shape[0])] = True
    near_object = cv2.dilate((alpha > 0.01).astype(np.uint8), np.ones((41, 41), np.uint8)) > 0
    plate_region = band & ~near_object

    pg = cv2.GaussianBlur(lp, (0, 0), 1.0)
    pgx = cv2.Sobel(pg, cv2.CV_32F, 1, 0, ksize=3)
    pgy = cv2.Sobel(pg, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(pgx, pgy)
    strong = plate_region & (mag > np.percentile(mag[plate_region], 99.0))
    plate_pts = np.argwhere(strong)
    if len(plate_pts) > args.max_edges:
        plate_pts = plate_pts[np.linspace(0, len(plate_pts) - 1, args.max_edges).astype(int)]
    pl_sigma, pl_prof = edge_sigma(lp, plate_pts, pgx, pgy, args.profile_radius, args.min_contrast)

    if not len(cg_sigma) or not len(pl_sigma):
        raise SystemExit("not enough qualifying edges; lower --min-contrast")

    s_cg, s_pl = float(np.median(cg_sigma)), float(np.median(pl_sigma))
    # Blurs add in quadrature, so the Gaussian that would take the CG edge to
    # the plate's is the quadrature difference of the two measured widths.
    implied_sigma = float(np.sqrt(max(s_pl ** 2 - s_cg ** 2, 0.0)))

    # --- Grain --------------------------------------------------------------
    plate_grain = grain_std(lp, plate_region)
    cg_grain = grain_std(lc, cv2.erode((alpha > 0.99).astype(np.uint8),
                                       np.ones((9, 9), np.uint8)) > 0)
    implied_grain = float(np.sqrt(max(plate_grain.get("std", 0) ** 2 -
                                      cg_grain.get("std", 0) ** 2, 0.0)))

    report = {
        "plate": os.path.basename(args.plate),
        "composite": os.path.basename(args.composite),
        "acutance": {
            "metric": "error-function fit to the edge profile; sigma in px along the gradient normal",
            "cg_edges": len(cg_sigma), "plate_edges": len(pl_sigma),
            "cg_sigma_px_median": round(s_cg, 3),
            "plate_sigma_px_median": round(s_pl, 3),
            "cg_sigma_px_p25_p75": [round(float(np.percentile(cg_sigma, 25)), 3),
                                    round(float(np.percentile(cg_sigma, 75)), 3)],
            "plate_sigma_px_p25_p75": [round(float(np.percentile(pl_sigma, 25)), 3),
                                       round(float(np.percentile(pl_sigma, 75)), 3)],
            "ratio_plate_over_cg": round(s_pl / max(s_cg, 1e-6), 3),
            "implied_gaussian_sigma_px": round(implied_sigma, 3),
        },
        "grain": {
            "metric": "std of (image - gaussian blur sigma 2) in the flattest 40% of each region",
            "plate": plate_grain, "cg": cg_grain,
            "ratio_plate_over_cg": round(plate_grain.get("std", 0) /
                                         max(cg_grain.get("std", 1e-9), 1e-9), 2),
            "implied_grain_sigma": round(implied_grain, 6),
        },
        "note": "measurement only; nothing is corrected here",
    }
    json.dump(report, open(os.path.join(args.out_dir, "sharpness_grain.json"), "w"), indent=2)
    print("SHARPNESS_GRAIN " + json.dumps(report, indent=2))

    np.save(os.path.join(args.out_dir, "cg_profile.npy"), cg_prof)
    np.save(os.path.join(args.out_dir, "plate_profile.npy"), pl_prof)
    np.save(os.path.join(args.out_dir, "cg_sigma.npy"), cg_sigma)
    np.save(os.path.join(args.out_dir, "plate_sigma.npy"), pl_sigma)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
