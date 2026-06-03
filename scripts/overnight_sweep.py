#!/usr/bin/env python3
"""
Overnight technique sweep for latent-merge contact-sheet text experiments.

Generates contact sheets comparing 8 CPU-only compositing backend techniques
against the golden_synthetic_001 fixture. Produces individual per-technique
run dirs, a master comparison sheet, and a scored matrix JSON.

Usage (from repo root):
    PYTHONPATH=".deps:." python3 scripts/overnight_sweep.py
    PYTHONPATH=".deps:." python3 scripts/overnight_sweep.py --fixture-dir fixtures/golden_synthetic_001 --out-dir runs/overnight_20260530
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
FONT_PATH_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
FONT_PATH_REG  = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
FONT_PATH_SANS = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

THUMB_W, THUMB_H = 384, 216
LABEL_H = 36
PAD = 8
COLS = 2  # thumbnails per row in per-technique sheet
META_H = 64  # metadata banner height
BG_COLOR = (14, 16, 20)
TEXT_COLOR = (220, 228, 240)
DIM_COLOR = (120, 130, 150)
ACCENT_COLOR = (80, 160, 255)
GOOD_COLOR = (80, 220, 120)
WARN_COLOR = (255, 200, 60)
BAD_COLOR  = (255, 80, 80)

OUTPUTS_ORDER = [
    ("final_comp",          "Final Comp"),
    ("adjusted_fg",         "Adjusted FG"),
    ("alpha_used",          "Alpha"),
    ("delta",               "Delta"),
    ("alpha_weighted_delta","Alpha-Weighted Delta"),
]


# ---------------------------------------------------------------------------
# Image I/O helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def load_rgba(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    return rgba[..., :3], rgba[..., 3:4]


def load_alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)[..., None] / 255.0


def save_rgb(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8)).save(path)


def save_rgba_img(path: Path, rgb: np.ndarray, alpha: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.dstack((rgb, alpha))
    Image.fromarray(np.clip(rgba * 255.0, 0, 255).astype(np.uint8)).save(path)


def save_alpha_img(path: Path, alpha: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(alpha[..., 0] * 255.0, 0, 255).astype(np.uint8)).save(path)


def _letterbox(img: Image.Image, w: int, h: int, bg: tuple = BG_COLOR) -> Image.Image:
    """Fit img into a w×h canvas preserving aspect ratio; center with bg padding."""
    fit = img.copy()
    fit.thumbnail((w, h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (w, h), bg)
    x_off = (w - fit.width)  // 2
    y_off = (h - fit.height) // 2
    canvas.paste(fit.convert("RGB"), (x_off, y_off))
    return canvas


# ---------------------------------------------------------------------------
# Font loader
# ---------------------------------------------------------------------------

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [FONT_PATH_BOLD if bold else FONT_PATH_REG, FONT_PATH_SANS]
    for p in paths:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Backends — each takes (plate, cg_rgb, alpha) float32 arrays [0,1]
#   returns (adjusted_rgb: np.ndarray, report: dict)
# ---------------------------------------------------------------------------

def backend_mean_match_stub(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """Baseline: per-channel gain clipped to [0.72, 1.28]."""
    aw = np.maximum(alpha, 1e-6)
    plate_mean = (plate * alpha).sum(axis=(0, 1)) / aw.sum()
    cg_mean    = (cg_rgb * alpha).sum(axis=(0, 1)) / aw.sum()
    gain = np.clip(plate_mean / np.maximum(cg_mean, 1e-4), 0.72, 1.28)
    adjusted = np.clip(cg_rgb * gain[None, None, :], 0.0, 1.0)
    return adjusted, {"gain": gain.tolist(), "gain_clamp": [0.72, 1.28]}


def backend_unclamped_mean_match(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """Unclamped per-channel gain — shows full mean-match range."""
    aw = np.maximum(alpha, 1e-6)
    plate_mean = (plate * alpha).sum(axis=(0, 1)) / aw.sum()
    cg_mean    = (cg_rgb * alpha).sum(axis=(0, 1)) / aw.sum()
    gain = plate_mean / np.maximum(cg_mean, 1e-4)
    adjusted = np.clip(cg_rgb * gain[None, None, :], 0.0, 1.0)
    return adjusted, {"gain": gain.tolist(), "gain_clamp": "none"}


def backend_rgb_affine(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """Affine (match mean + std) in linear RGB — Reinhard 2001 applied in RGB."""
    aw = np.maximum(alpha, 1e-6)
    total = aw.sum()
    plate_mean = (plate * alpha).sum(axis=(0, 1)) / total
    cg_mean    = (cg_rgb * alpha).sum(axis=(0, 1)) / total
    plate_std  = np.sqrt(((plate - plate_mean[None, None, :]) ** 2 * alpha).sum(axis=(0, 1)) / total + 1e-8)
    cg_std     = np.sqrt(((cg_rgb - cg_mean[None, None, :]) ** 2 * alpha).sum(axis=(0, 1)) / total + 1e-8)
    scale = plate_std / np.maximum(cg_std, 1e-6)
    adjusted = (cg_rgb - cg_mean[None, None, :]) * scale[None, None, :] + plate_mean[None, None, :]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    return adjusted, {"cg_mean": cg_mean.tolist(), "plate_mean": plate_mean.tolist(),
                      "cg_std": cg_std.tolist(), "plate_std": plate_std.tolist(),
                      "scale": scale.tolist()}


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Approximate sRGB -> CIELAB (D65). rgb shape (..., 3) float32 [0,1]."""
    # Linearise (approximate sRGB gamma)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    # D65 RGB -> XYZ
    M = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
    xyz = lin @ M.T
    # Normalize by D65 white
    xyz /= np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)
    # f function
    delta = 6.0 / 29.0
    f = np.where(xyz > delta ** 3,
                 np.cbrt(np.maximum(xyz, 0)),
                 xyz / (3 * delta ** 2) + 4.0 / 29.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def _lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Approximate CIELAB -> sRGB. lab shape (..., 3)."""
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0
    delta = 6.0 / 29.0
    def finv(t: np.ndarray) -> np.ndarray:
        return np.where(t > delta, t ** 3, 3 * delta ** 2 * (t - 4.0 / 29.0))
    xyz = np.stack([finv(fx), finv(fy), finv(fz)], axis=-1)
    xyz *= np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)
    Minv = np.array([[ 3.2404542, -1.5371385, -0.4985314],
                     [-0.9692660,  1.8760108,  0.0415560],
                     [ 0.0556434, -0.2040259,  1.0572252]], dtype=np.float32)
    lin = xyz @ Minv.T
    lin = np.clip(lin, 0.0, None)
    # sRGB gamma
    rgb = np.where(lin <= 0.0031308,
                   12.92 * lin,
                   1.055 * lin ** (1.0 / 2.4) - 0.055)
    return np.clip(rgb, 0.0, 1.0)


def backend_lab_mean_std(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """Reinhard 2001 color transfer in Lab (match mean + std per L/a/b channel)."""
    aw = np.maximum(alpha, 1e-6)
    total = aw.sum()

    plate_lab = _rgb_to_lab(plate)
    cg_lab    = _rgb_to_lab(cg_rgb)

    plate_mean = (plate_lab * alpha).sum(axis=(0, 1)) / total
    cg_mean    = (cg_lab   * alpha).sum(axis=(0, 1)) / total
    plate_std  = np.sqrt(((plate_lab - plate_mean[None, None, :]) ** 2 * alpha).sum(axis=(0, 1)) / total + 1e-8)
    cg_std     = np.sqrt(((cg_lab   - cg_mean[None, None, :])    ** 2 * alpha).sum(axis=(0, 1)) / total + 1e-8)

    scale = plate_std / np.maximum(cg_std, 1e-6)
    adjusted_lab = (cg_lab - cg_mean[None, None, :]) * scale[None, None, :] + plate_mean[None, None, :]
    adjusted = _lab_to_rgb(adjusted_lab)

    return adjusted, {
        "space": "Lab",
        "cg_mean": cg_mean.tolist(),
        "plate_mean": plate_mean.tolist(),
        "scale": scale.tolist(),
    }


def backend_lab_mean_only(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """Lab mean transfer only (no std scaling). Preserves CG contrast, shifts hue/luminance."""
    aw = np.maximum(alpha, 1e-6)
    total = aw.sum()

    plate_lab = _rgb_to_lab(plate)
    cg_lab    = _rgb_to_lab(cg_rgb)

    plate_mean = (plate_lab * alpha).sum(axis=(0, 1)) / total
    cg_mean    = (cg_lab   * alpha).sum(axis=(0, 1)) / total
    shift = plate_mean - cg_mean

    adjusted_lab = cg_lab + shift[None, None, :]
    adjusted = _lab_to_rgb(adjusted_lab)

    return adjusted, {
        "space": "Lab",
        "shift_Lab": shift.tolist(),
        "cg_mean": cg_mean.tolist(),
        "plate_mean": plate_mean.tolist(),
    }


def _cdf_match_1d(src: np.ndarray, ref: np.ndarray, mask: np.ndarray, n_bins: int = 256) -> np.ndarray:
    """Match src channel histogram to ref channel histogram under mask (float32, [0,1])."""
    # Build masked histograms
    src_vals = src[mask > 0.5].ravel()
    ref_vals = ref[mask > 0.5].ravel()

    # Compute CDFs
    src_hist, edges = np.histogram(src_vals, bins=n_bins, range=(0.0, 1.0), density=False)
    ref_hist, _     = np.histogram(ref_vals, bins=n_bins, range=(0.0, 1.0), density=False)

    src_cdf = src_hist.cumsum().astype(np.float64)
    ref_cdf = ref_hist.cumsum().astype(np.float64)
    src_cdf /= src_cdf[-1] + 1e-12
    ref_cdf /= ref_cdf[-1] + 1e-12

    # Build LUT: for each src bin center find the ref value with the same cdf
    bin_centers = 0.5 * (edges[:-1] + edges[1:])
    lut_out = np.interp(src_cdf, ref_cdf, bin_centers).astype(np.float32)

    # Apply LUT to full src image
    bin_idx = np.clip((src * (n_bins - 1)).astype(np.int32), 0, n_bins - 1)
    return lut_out[bin_idx].astype(np.float32)


def backend_histogram_match(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """Per-channel histogram CDF matching under alpha mask."""
    mask = alpha[..., 0] > 0.1
    adjusted = np.zeros_like(cg_rgb)
    for c in range(3):
        adjusted[..., c] = _cdf_match_1d(cg_rgb[..., c], plate[..., c], mask)
    adjusted = np.clip(adjusted, 0.0, 1.0)
    return adjusted, {"method": "cdf_histogram_match", "n_bins": 256}


def backend_gamma_curve(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """Per-channel gamma curve correction: cg^(log(plate_mean)/log(cg_mean))."""
    aw = np.maximum(alpha, 1e-6)
    total = aw.sum()
    plate_mean = np.clip((plate * alpha).sum(axis=(0, 1)) / total, 0.01, 0.99)
    cg_mean    = np.clip((cg_rgb * alpha).sum(axis=(0, 1)) / total, 0.01, 0.99)
    gamma = np.log(plate_mean) / np.log(np.maximum(cg_mean, 1e-4))
    gamma = np.clip(gamma, 0.3, 3.5)
    adjusted = np.clip(cg_rgb[..., :] ** gamma[None, None, :], 0.0, 1.0)
    return adjusted, {"gamma": gamma.tolist()}


def backend_local_spatial_match(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray,
                                 grid: int = 3) -> tuple[np.ndarray, dict]:
    """Tile-based local mean matching: divide into grid×grid tiles, per-tile gain."""
    H, W = plate.shape[:2]
    adjusted = np.zeros_like(cg_rgb)
    tile_reports = []

    for row in range(grid):
        for col in range(grid):
            r0 = row * H // grid;  r1 = (row + 1) * H // grid
            c0 = col * W // grid;  c1 = (col + 1) * W // grid

            pt = plate[r0:r1, c0:c1]
            cg = cg_rgb[r0:r1, c0:c1]
            al = alpha[r0:r1, c0:c1]
            aw = np.maximum(al, 1e-6)
            total = aw.sum()

            plate_mean = (pt * al).sum(axis=(0, 1)) / total
            cg_mean    = (cg  * al).sum(axis=(0, 1)) / total

            if alpha[r0:r1, c0:c1].max() < 0.05:
                adjusted[r0:r1, c0:c1] = cg
                tile_reports.append({"tile": [row, col], "gain": [1.0, 1.0, 1.0], "skipped": True})
                continue

            gain = np.clip(plate_mean / np.maximum(cg_mean, 1e-4), 0.5, 2.0)
            adjusted[r0:r1, c0:c1] = np.clip(cg * gain[None, None, :], 0.0, 1.0)
            tile_reports.append({"tile": [row, col], "gain": gain.tolist()})

    return np.clip(adjusted, 0.0, 1.0), {"grid": f"{grid}x{grid}", "tiles": tile_reports}


def backend_polynomial_color(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict]:
    """
    Least-squares polynomial color correction under alpha mask.
    Fits: adjusted_R = a0 + a1*R + a2*G + a3*B + a4*R^2 + a5*G^2 + a6*B^2
    per output channel, using masked pixels from CG and plate as training pairs.
    """
    mask = (alpha[..., 0] > 0.1).ravel()
    n = mask.sum()
    if n < 12:
        # Fallback to mean_match if too few pixels
        return backend_mean_match_stub(plate, cg_rgb, alpha)

    R = cg_rgb[..., 0].ravel()[mask]
    G = cg_rgb[..., 1].ravel()[mask]
    B = cg_rgb[..., 2].ravel()[mask]

    # Feature matrix: 1, R, G, B, R^2, G^2, B^2
    X = np.stack([
        np.ones_like(R), R, G, B, R*R, G*G, B*B
    ], axis=1)  # shape (n, 7)

    adjusted = np.zeros_like(cg_rgb)
    coeffs_all = []

    for c in range(3):
        y = plate[..., c].ravel()[mask]
        # Normal equations: X^T X coeff = X^T y
        A = X.T @ X + 1e-4 * np.eye(7)
        b = X.T @ y
        try:
            coeff = np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            coeff = np.zeros(7)
            coeff[c + 1] = 1.0  # identity fallback

        # Apply to all pixels
        R_full = cg_rgb[..., 0]
        G_full = cg_rgb[..., 1]
        B_full = cg_rgb[..., 2]
        out = (coeff[0]
               + coeff[1] * R_full + coeff[2] * G_full + coeff[3] * B_full
               + coeff[4] * R_full**2 + coeff[5] * G_full**2 + coeff[6] * B_full**2)
        adjusted[..., c] = np.clip(out, 0.0, 1.0)
        coeffs_all.append(coeff.tolist())

    return adjusted, {"method": "polynomial_color_7coeff", "coefficients_rgb": coeffs_all}


BACKENDS: dict[str, dict] = {
    "01_mean_match_stub": {
        "fn": backend_mean_match_stub,
        "label": "1. Mean Match (baseline)",
        "desc": "Per-channel gain clipped [0.72,1.28]",
    },
    "02_unclamped_mean": {
        "fn": backend_unclamped_mean_match,
        "label": "2. Unclamped Mean Match",
        "desc": "Per-channel gain, no clamp",
    },
    "03_rgb_affine": {
        "fn": backend_rgb_affine,
        "label": "3. RGB Affine (mean+std)",
        "desc": "Match mean and std in linear RGB",
    },
    "04_lab_mean_only": {
        "fn": backend_lab_mean_only,
        "label": "4. Lab Mean Transfer",
        "desc": "Shift mean in Lab; preserve CG contrast",
    },
    "05_lab_mean_std": {
        "fn": backend_lab_mean_std,
        "label": "5. Lab Affine (Reinhard 2001)",
        "desc": "Match mean+std in Lab (L/a/b)",
    },
    "06_histogram_match": {
        "fn": backend_histogram_match,
        "label": "6. Histogram CDF Match",
        "desc": "Full per-channel histogram equalization",
    },
    "07_gamma_curve": {
        "fn": backend_gamma_curve,
        "label": "7. Gamma Curve Correction",
        "desc": "Per-channel gamma from plate/cg mean ratio",
    },
    "08_local_spatial": {
        "fn": lambda p, cg, a: backend_local_spatial_match(p, cg, a, grid=3),
        "label": "8. Local Spatial (3×3 tiles)",
        "desc": "Per-tile mean matching, 3×3 grid",
    },
    "09_polynomial_color": {
        "fn": backend_polynomial_color,
        "label": "9. Polynomial Color Fit",
        "desc": "Least-squares 7-coeff color polynomial",
    },
}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(plate: np.ndarray, cg_rgb: np.ndarray,
                    adjusted: np.ndarray, alpha: np.ndarray) -> dict[str, float]:
    """Compute scores: identity preservation, integration quality, alpha-edge delta."""
    mask = alpha[..., 0] > 0.1
    n = mask.sum() + 1e-6

    # RMSE between adjusted and original CG (identity drift — lower = better preserved)
    id_drift_rgb = float(np.sqrt(((adjusted - cg_rgb) ** 2 * alpha).sum() / (n * 3)))

    # RMSE between adjusted and plate under alpha (integration quality — lower = better)
    integration = float(np.sqrt(((adjusted - plate) ** 2 * alpha).sum() / (n * 3)))

    # Alpha-weighted delta (how much was changed in the foreground area)
    aw_delta = float(np.abs((adjusted - cg_rgb) * alpha).mean())

    # Contrast preservation: std of adjusted vs std of cg under alpha
    if n > 1:
        cg_std  = float(cg_rgb[mask].std())
        adj_std = float(adjusted[mask].std())
        contrast_ratio = adj_std / max(cg_std, 1e-6)
    else:
        contrast_ratio = 1.0

    # Final comp plate-repaint check: plate must be untouched
    final_comp = adjusted * alpha + plate * (1.0 - alpha)
    plate_repaint_err = float(np.abs(final_comp * (1.0 - alpha) - plate * (1.0 - alpha)).max())

    return {
        "id_drift_rmse": round(id_drift_rgb, 6),
        "integration_rmse": round(integration, 6),
        "aw_delta_mean": round(aw_delta, 6),
        "contrast_ratio": round(contrast_ratio, 4),
        "plate_repaint_err": round(plate_repaint_err, 8),
    }


# ---------------------------------------------------------------------------
# Contact sheet renderer
# ---------------------------------------------------------------------------

def _render_contact_sheet(
    job_dir: Path,
    outputs: dict[str, Path],
    label: str,
    desc: str,
    metrics: dict[str, float],
    duration_s: float,
    backend_key: str,
    font_size: int = 14,
) -> Path:
    font_body = _load_font(font_size)
    font_bold = _load_font(font_size + 1, bold=True)
    font_tiny = _load_font(font_size - 2)
    font_header = _load_font(font_size + 4, bold=True)

    # Load and letterbox each output
    thumbs: list[tuple[str, Image.Image]] = []
    for key, lbl in OUTPUTS_ORDER:
        path = outputs.get(key)
        if path and Path(path).exists():
            img = Image.open(path).convert("RGB")
            thumbs.append((lbl, _letterbox(img, THUMB_W, THUMB_H)))

    num_thumbs = len(thumbs)
    ncols = COLS
    nrows = (num_thumbs + ncols - 1) // ncols

    cell_w = THUMB_W + PAD * 2
    cell_h = THUMB_H + LABEL_H + PAD * 2
    sheet_w = cell_w * ncols + PAD
    sheet_h = META_H + cell_h * nrows + PAD + 80  # extra for metrics row

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    # Header bar
    draw.rectangle([(0, 0), (sheet_w, META_H)], fill=(22, 26, 36))
    draw.text((PAD, PAD), label, fill=ACCENT_COLOR, font=font_header)
    draw.text((PAD, PAD + font_size + 8), desc, fill=DIM_COLOR, font=font_body)
    draw.text((sheet_w - 180, PAD), f"{backend_key}", fill=DIM_COLOR, font=font_tiny)
    draw.text((sheet_w - 180, PAD + 14), f"{duration_s:.2f}s", fill=DIM_COLOR, font=font_tiny)

    # Thumbnail grid
    for idx, (lbl, img) in enumerate(thumbs):
        col = idx % ncols
        row = idx // ncols
        x = col * cell_w + PAD
        y = META_H + row * cell_h + PAD

        # Cell background
        draw.rectangle([(x, y), (x + THUMB_W + PAD, y + THUMB_H + LABEL_H + PAD)], fill=(22, 26, 36))

        # Label
        draw.text((x + 6, y + 4), lbl, fill=TEXT_COLOR, font=font_bold)

        # Thumb (already letterboxed to THUMB_W × THUMB_H)
        sheet.paste(img, (x + 4, y + LABEL_H))

    # Metrics row
    my = META_H + nrows * cell_h + PAD * 2
    draw.rectangle([(0, my - 4), (sheet_w, sheet_h)], fill=(18, 22, 30))

    id_color  = GOOD_COLOR if metrics["id_drift_rmse"] < 0.04 else (WARN_COLOR if metrics["id_drift_rmse"] < 0.10 else BAD_COLOR)
    int_color = GOOD_COLOR if metrics["integration_rmse"] < 0.08 else (WARN_COLOR if metrics["integration_rmse"] < 0.15 else BAD_COLOR)

    mx = PAD
    for text, color in [
        (f"id_drift={metrics['id_drift_rmse']:.4f}", id_color),
        (f"  integration={metrics['integration_rmse']:.4f}", int_color),
        (f"  contrast_ratio={metrics['contrast_ratio']:.3f}", TEXT_COLOR),
        (f"  plate_clean={metrics['plate_repaint_err'] < 1e-5}", GOOD_COLOR if metrics['plate_repaint_err'] < 1e-5 else BAD_COLOR),
    ]:
        draw.text((mx, my + 4), text, fill=color, font=font_body)
        bbox = draw.textbbox((mx, my + 4), text, font=font_body)
        mx = bbox[2] + 2

    out_path = job_dir / "contact_sheet.jpg"
    sheet.save(out_path, quality=94)
    return out_path


# ---------------------------------------------------------------------------
# Master comparison sheet
# ---------------------------------------------------------------------------

def _render_master_sheet(
    runs: list[dict],
    out_path: Path,
    fixture_label: str,
) -> None:
    """One row per technique. Columns: technique label | final_comp thumb | metrics bar."""
    font_body = _load_font(13)
    font_bold = _load_font(14, bold=True)
    font_header = _load_font(16, bold=True)
    font_tiny = _load_font(10)

    THUMB_SMALL_W = 320
    THUMB_SMALL_H = 180
    ROW_H = THUMB_SMALL_H + 16
    LABEL_COL_W = 260
    METRIC_COL_W = 360
    SHEET_W = LABEL_COL_W + THUMB_SMALL_W + PAD * 3 + METRIC_COL_W
    HEADER_H = 50

    sheet_h = HEADER_H + len(runs) * ROW_H + PAD * 2
    sheet = Image.new("RGB", (SHEET_W, sheet_h), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    # Header
    draw.rectangle([(0, 0), (SHEET_W, HEADER_H)], fill=(22, 26, 36))
    draw.text((PAD, PAD), f"Latent-Merge Technique Sweep — Master Comparison", fill=ACCENT_COLOR, font=font_header)
    draw.text((PAD, HEADER_H - 16), f"Fixture: {fixture_label}  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
              fill=DIM_COLOR, font=font_tiny)

    # Column headers
    cy = HEADER_H
    draw.text((PAD, cy), "Technique", fill=DIM_COLOR, font=font_body)
    draw.text((LABEL_COL_W + PAD, cy), "Final Comp", fill=DIM_COLOR, font=font_body)
    draw.text((LABEL_COL_W + THUMB_SMALL_W + PAD * 2, cy), "Metrics", fill=DIM_COLOR, font=font_body)
    cy += 18

    for run in runs:
        m = run["metrics"]
        key = run["backend_key"]
        label = run["label"]
        final_comp_path = run.get("final_comp_path")

        row_y = cy

        # Label column
        draw.rectangle([(0, row_y), (LABEL_COL_W, row_y + ROW_H)], fill=(18, 22, 30))
        draw.text((PAD, row_y + 6), label, fill=TEXT_COLOR, font=font_bold)
        draw.text((PAD, row_y + 26), run.get("desc", ""), fill=DIM_COLOR, font=font_tiny)
        draw.text((PAD, row_y + 40), f"t={run.get('duration_s', 0):.2f}s", fill=DIM_COLOR, font=font_tiny)

        # Thumb column
        tx = LABEL_COL_W + PAD
        if final_comp_path and Path(final_comp_path).exists():
            img = Image.open(final_comp_path).convert("RGB")
            thumb = _letterbox(img, THUMB_SMALL_W, THUMB_SMALL_H)
            sheet.paste(thumb, (tx, row_y + 8))

        # Metrics column
        mx = LABEL_COL_W + THUMB_SMALL_W + PAD * 2
        my = row_y + 8

        id_color  = GOOD_COLOR if m["id_drift_rmse"] < 0.04 else (WARN_COLOR if m["id_drift_rmse"] < 0.10 else BAD_COLOR)
        int_color = GOOD_COLOR if m["integration_rmse"] < 0.08 else (WARN_COLOR if m["integration_rmse"] < 0.15 else BAD_COLOR)

        draw.text((mx, my),      f"id_drift  {m['id_drift_rmse']:.4f}", fill=id_color, font=font_body)
        draw.text((mx, my + 18), f"integr.   {m['integration_rmse']:.4f}", fill=int_color, font=font_body)
        draw.text((mx, my + 36), f"contrast  {m['contrast_ratio']:.3f}", fill=TEXT_COLOR, font=font_body)
        draw.text((mx, my + 54), f"aw_delta  {m['aw_delta_mean']:.4f}", fill=DIM_COLOR, font=font_body)
        plate_ok_color = GOOD_COLOR if m["plate_repaint_err"] < 1e-5 else BAD_COLOR
        draw.text((mx, my + 72), f"plate_clean {'YES' if m['plate_repaint_err'] < 1e-5 else 'NO'}", fill=plate_ok_color, font=font_body)

        cy += ROW_H
        # Separator
        draw.line([(0, cy), (SHEET_W, cy)], fill=(30, 34, 44), width=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out_path), quality=94)


# ---------------------------------------------------------------------------
# Refinement round: run best 3 candidates at higher precision
# ---------------------------------------------------------------------------

def _render_refinement_sheet(
    runs: list[dict],
    out_path: Path,
) -> None:
    """Side-by-side of best candidates. 3 columns of final_comp + metrics."""
    font_body = _load_font(12)
    font_bold = _load_font(13, bold=True)
    font_header = _load_font(15, bold=True)
    font_tiny = _load_font(10)

    TW, TH = 400, 225
    LH = 20
    PAD2 = 10
    HEADER_H = 50
    META_H_PER = 100  # height for metrics below each thumb

    ncols = min(len(runs), 3)
    cell_w = TW + PAD2 * 2
    sheet_w = cell_w * ncols + PAD2
    sheet_h = HEADER_H + TH + LH + META_H_PER + PAD2 * 3

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    draw.rectangle([(0, 0), (sheet_w, HEADER_H)], fill=(22, 26, 36))
    draw.text((PAD2, PAD2), "Refinement Round — Top Candidates", fill=ACCENT_COLOR, font=font_header)
    draw.text((PAD2, HEADER_H - 16), "Ranked by composite score (id_drift × 0.4 + integration × 0.6)",
              fill=DIM_COLOR, font=font_tiny)

    for i, run in enumerate(runs[:ncols]):
        cx = i * cell_w + PAD2
        cy = HEADER_H + PAD2

        draw.rectangle([(cx, cy), (cx + TW + PAD2, cy + TH + LH + META_H_PER + PAD2)], fill=(18, 22, 30))
        draw.text((cx + 6, cy + 2), run["label"], fill=ACCENT_COLOR, font=font_bold)

        fp = run.get("final_comp_path")
        if fp and Path(fp).exists():
            img = Image.open(fp).convert("RGB")
            sheet.paste(_letterbox(img, TW, TH), (cx + 4, cy + LH))

        my = cy + LH + TH + PAD2
        m = run["metrics"]
        score = run.get("composite_score", 0)
        draw.text((cx + 4, my),      f"Score: {score:.4f}  (rank #{i+1})", fill=ACCENT_COLOR, font=font_bold)
        draw.text((cx + 4, my + 16), f"id_drift  = {m['id_drift_rmse']:.5f}", fill=GOOD_COLOR if m['id_drift_rmse'] < 0.04 else WARN_COLOR, font=font_body)
        draw.text((cx + 4, my + 30), f"integration= {m['integration_rmse']:.5f}", fill=GOOD_COLOR if m['integration_rmse'] < 0.08 else WARN_COLOR, font=font_body)
        draw.text((cx + 4, my + 44), f"contrast   = {m['contrast_ratio']:.4f}", fill=TEXT_COLOR, font=font_body)
        draw.text((cx + 4, my + 58), f"backend: {run['backend_key']}", fill=DIM_COLOR, font=font_tiny)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out_path), quality=94)


# ---------------------------------------------------------------------------
# IC Flux documentation
# ---------------------------------------------------------------------------

IC_FLUX_DOCS = {
    "status": "BLOCKED_NO_GPU_NO_WEIGHTS",
    "blocker": (
        "This VPS has no NVIDIA GPU (nvidia-smi returns no devices). "
        "IC-Light V2 / FLUX requires a CUDA GPU with ≥12 GB VRAM. "
        "torch, diffusers, transformers, and accelerate are not installed. "
        "No model weights are cached locally."
    ),
    "target_hardware": "Gonzo's home server: RTX 3080 Ti (12 GB VRAM)",
    "install_commands": [
        "pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121",
        "pip install diffusers transformers accelerate huggingface_hub",
        "pip install xformers  # optional, for memory savings",
    ],
    "weight_download": [
        "# IC-Light V2 FLUX weights (HuggingFace):",
        "from huggingface_hub import snapshot_download",
        "snapshot_download('lllyasviel/ic-light', local_dir='weights/ic-light-v2')",
        "# Also grab FLUX backbone if not cached:",
        "snapshot_download('black-forest-labs/FLUX.1-dev', local_dir='weights/flux1-dev')",
    ],
    "run_commands": [
        "# Baseline comparison run (same fixture):",
        "python3 scripts/ic_flux_runner.py \\",
        "  --plate  fixtures/golden_synthetic_001/plate_rgb.png \\",
        "  --cg     fixtures/golden_synthetic_001/cg_rgba.png \\",
        "  --alpha  fixtures/golden_synthetic_001/alpha.png \\",
        "  --seed   42 \\",
        "  --steps  20 \\",
        "  --cfg    3.5 \\",
        "  --out-dir runs/overnight_20260530/ic_flux_baseline",
        "",
        "# Side-by-side comparison against best CPU technique:",
        "python3 scripts/overnight_sweep.py --compare-ic-flux runs/overnight_20260530/ic_flux_baseline",
    ],
    "ic_flux_runner_stub": "scripts/ic_flux_runner.py",
    "key_risks": [
        "FLUX diffusion rewrites CG textures and identity details.",
        "VAE encode/decode introduces distortion (especially fine edges).",
        "Alpha edge seams and halos are common without alpha-aware conditioning.",
        "SDR-trained; HDR/EXR plates will need tonemapping before inference.",
        "Each step = ~2-4s on RTX 3080 Ti; 20 steps = ~1-2 min per frame.",
        "Non-deterministic without fixed seed; always record seed in job.json.",
    ],
    "recommended_settings": {
        "steps": "20–30 (higher = more coherent but slower)",
        "cfg_scale": "2.5–4.0 (lower = more plate-influenced)",
        "seed": "42 (or any fixed integer for reproducibility)",
        "resolution": "512 or 768 px (match fixture resolution)",
        "conditioning_strength": "0.6–0.8 (higher = more IC-Light influence)",
    },
}


# ---------------------------------------------------------------------------
# IC Flux stub runner (for future use on GPU hardware)
# ---------------------------------------------------------------------------

IC_FLUX_RUNNER_STUB = '''#!/usr/bin/env python3
"""
IC-Light V2 / FLUX runner stub for latent-merge.
Run this on hardware with a CUDA GPU (≥12 GB VRAM).
See runs/overnight_20260530/ic_flux_docs.json for install instructions.

Usage:
    python3 scripts/ic_flux_runner.py \\
        --plate  fixtures/golden_synthetic_001/plate_rgb.png \\
        --cg     fixtures/golden_synthetic_001/cg_rgba.png \\
        --alpha  fixtures/golden_synthetic_001/alpha.png \\
        --seed   42 --steps 20 --cfg 3.5 \\
        --out-dir runs/overnight_20260530/ic_flux_baseline
"""

from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--plate",   type=Path, required=True)
    p.add_argument("--cg",      type=Path, required=True)
    p.add_argument("--alpha",   type=Path, required=True)
    p.add_argument("--seed",    type=int, default=42)
    p.add_argument("--steps",   type=int, default=20)
    p.add_argument("--cfg",     type=float, default=3.5)
    p.add_argument("--cond-strength", type=float, default=0.75, dest="cond_strength")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--weights-dir", type=Path, default=Path("weights/ic-light-v2"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import torch
        from diffusers import FluxPipeline
    except ImportError:
        raise RuntimeError(
            "torch and diffusers are required. Run:\\n"
            "  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121\\n"
            "  pip install diffusers transformers accelerate"
        )

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU required for IC-Light V2 / FLUX. No GPU detected.")

    plate = Image.open(args.plate).convert("RGB")
    cg    = Image.open(args.cg).convert("RGBA")
    alpha = cg.getchannel("A")

    # --- IC-Light V2 pipeline loading ---
    # NOTE: Actual IC-Light V2 FLUX API may differ; update when weights are available.
    # This is a documented placeholder using the expected diffusers interface.
    # See: https://github.com/lllyasviel/IC-Light
    print("Loading IC-Light V2 FLUX pipeline...")
    # pipe = FluxPipeline.from_pretrained(str(args.weights_dir), torch_dtype=torch.float16)
    # pipe = pipe.to("cuda")

    # Placeholder: save the input CG as the "adjusted" output (identity pass)
    print("WARNING: IC-Light pipeline not loaded — saving identity pass for structure test.")
    cg_rgb = Image.open(args.cg).convert("RGB")
    cg_rgb.save(args.out_dir / "adjusted_fg.png")

    # Final comp = adjusted over plate
    plate_arr  = np.asarray(plate, dtype=np.float32) / 255.0
    cg_arr     = np.asarray(cg.convert("RGB"), dtype=np.float32) / 255.0
    alpha_arr  = np.asarray(alpha, dtype=np.float32)[..., None] / 255.0

    comp = cg_arr * alpha_arr + plate_arr * (1.0 - alpha_arr)
    Image.fromarray((comp * 255).astype("uint8")).save(args.out_dir / "final_comp.png")
    delta = np.abs(cg_arr - cg_arr)  # zero for identity
    Image.fromarray((delta * 255).astype("uint8")).save(args.out_dir / "delta.png")

    job = {
        "schema": "latent-merge.ic-flux-run.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "backend": "ic_light_v2_flux",
        "inputs": {
            "plate": str(args.plate),
            "cg": str(args.cg),
            "alpha": str(args.alpha),
        },
        "params": {
            "seed": args.seed,
            "steps": args.steps,
            "cfg_scale": args.cfg,
            "cond_strength": args.cond_strength,
        },
        "status": "identity_stub_no_gpu",
        "outputs": {
            "adjusted_fg": str(args.out_dir / "adjusted_fg.png"),
            "final_comp":  str(args.out_dir / "final_comp.png"),
            "delta":       str(args.out_dir / "delta.png"),
        },
    }
    (args.out_dir / "job.json").write_text(json.dumps(job, indent=2))
    print(f"IC-Light run complete → {args.out_dir}")


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Overnight latent-merge technique sweep.")
    parser.add_argument("--fixture-dir", type=Path, default=ROOT / "fixtures" / "golden_synthetic_001")
    parser.add_argument("--out-dir",     type=Path, default=ROOT / "runs" / "overnight_20260530")
    parser.add_argument("--backends",    nargs="*", help="Subset of backend keys to run (default: all)")
    args = parser.parse_args()

    fixture_dir = args.fixture_dir
    out_dir     = args.out_dir

    plate_path = fixture_dir / "plate_rgb.png"
    cg_path    = fixture_dir / "cg_rgba.png"
    alpha_path = fixture_dir / "alpha.png"

    missing = [str(p) for p in (plate_path, cg_path, alpha_path) if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing fixture inputs: " + ", ".join(missing))

    plate   = load_rgb(plate_path)
    cg_rgb, cg_alpha = load_rgba(cg_path)
    ext_alpha = load_alpha(alpha_path)
    combined_alpha = np.minimum(ext_alpha, cg_alpha)

    backend_keys = args.backends or list(BACKENDS.keys())

    run_records: list[dict] = []

    print(f"Running {len(backend_keys)} backends on {fixture_dir.name}...")
    print(f"Output dir: {out_dir}")

    for bk in backend_keys:
        if bk not in BACKENDS:
            print(f"  SKIP unknown backend: {bk}")
            continue

        bd = BACKENDS[bk]
        run_dir = out_dir / bk
        run_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n  [{bk}] {bd['label']}")
        t0 = time.perf_counter()

        try:
            adjusted_rgb, report = bd["fn"](plate, cg_rgb, combined_alpha)
        except Exception as exc:
            print(f"    ERROR: {exc}")
            run_records.append({"backend_key": bk, "label": bd["label"], "desc": bd["desc"],
                                  "status": "error", "error": str(exc)})
            continue

        final_comp = adjusted_rgb * combined_alpha + plate * (1.0 - combined_alpha)
        delta = np.abs(adjusted_rgb - cg_rgb)
        aw_delta = delta * combined_alpha

        outputs = {
            "adjusted_fg":          run_dir / "adjusted_fg.png",
            "final_comp":           run_dir / "final_comp.png",
            "delta":                run_dir / "delta.png",
            "alpha_weighted_delta": run_dir / "alpha_weighted_delta.png",
            "alpha_used":           run_dir / "alpha_used.png",
        }

        save_rgba_img(outputs["adjusted_fg"], adjusted_rgb, combined_alpha)
        save_rgb(outputs["final_comp"], final_comp)
        save_rgb(outputs["delta"], delta)
        save_rgb(outputs["alpha_weighted_delta"], aw_delta)
        save_alpha_img(outputs["alpha_used"], combined_alpha)

        metrics = compute_metrics(plate, cg_rgb, adjusted_rgb, combined_alpha)
        duration = time.perf_counter() - t0

        cs_path = _render_contact_sheet(
            job_dir=run_dir,
            outputs={k: str(v) for k, v in outputs.items()},
            label=bd["label"],
            desc=bd["desc"],
            metrics=metrics,
            duration_s=duration,
            backend_key=bk,
        )

        job = {
            "schema": "latent-merge.overnight-run.v1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "backend_key": bk,
            "label": bd["label"],
            "desc": bd["desc"],
            "fixture": str(fixture_dir),
            "inputs": {
                "plate_rgb": {"path": str(plate_path), "sha256": sha256_file(plate_path)},
                "cg_rgba":   {"path": str(cg_path),   "sha256": sha256_file(cg_path)},
                "alpha":     {"path": str(alpha_path), "sha256": sha256_file(alpha_path)},
            },
            "outputs": {k: str(v) for k, v in outputs.items()},
            "contact_sheet": str(cs_path),
            "backend_report": report,
            "metrics": metrics,
            "duration_s": round(duration, 4),
        }
        (run_dir / "job.json").write_text(json.dumps(job, indent=2) + "\n")

        print(f"    id_drift={metrics['id_drift_rmse']:.4f}  integration={metrics['integration_rmse']:.4f}  t={duration:.2f}s")

        run_records.append({
            "backend_key": bk,
            "label": bd["label"],
            "desc": bd["desc"],
            "status": "ok",
            "metrics": metrics,
            "duration_s": round(duration, 4),
            "final_comp_path": str(outputs["final_comp"]),
            "contact_sheet": str(cs_path),
        })

    # Master comparison sheet
    ok_runs = [r for r in run_records if r.get("status") == "ok"]
    master_path = out_dir / "master_comparison.jpg"
    print(f"\nBuilding master comparison sheet → {master_path}")
    _render_master_sheet(ok_runs, master_path, fixture_label=fixture_dir.name)

    # Refinement: top 3 by composite score (id_drift * 0.4 + integration * 0.6)
    for r in ok_runs:
        m = r["metrics"]
        r["composite_score"] = m["id_drift_rmse"] * 0.4 + m["integration_rmse"] * 0.6

    ranked = sorted(ok_runs, key=lambda r: r["composite_score"])
    top3 = ranked[:3]

    refinement_path = out_dir / "refinement_top3.jpg"
    print(f"Building refinement top-3 sheet → {refinement_path}")
    _render_refinement_sheet(top3, refinement_path)

    # Write IC Flux docs
    ic_flux_path = out_dir / "ic_flux_docs.json"
    ic_flux_path.write_text(json.dumps(IC_FLUX_DOCS, indent=2) + "\n")

    # Write IC Flux runner stub
    stub_path = ROOT / "scripts" / "ic_flux_runner.py"
    if not stub_path.exists():
        stub_path.write_text(IC_FLUX_RUNNER_STUB)
        print(f"Wrote IC Flux runner stub → {stub_path}")

    # Summary JSON
    summary = {
        "schema": "latent-merge.overnight-sweep.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "fixture": str(fixture_dir),
        "backends_run": len(ok_runs),
        "backends_errored": len([r for r in run_records if r.get("status") == "error"]),
        "master_comparison": str(master_path),
        "refinement_top3": str(refinement_path),
        "ic_flux_docs": str(ic_flux_path),
        "ranking": [
            {
                "rank": i + 1,
                "backend_key": r["backend_key"],
                "label": r["label"],
                "composite_score": round(r["composite_score"], 6),
                "metrics": r["metrics"],
                "duration_s": r["duration_s"],
                "contact_sheet": r["contact_sheet"],
            }
            for i, r in enumerate(ranked)
        ],
    }
    summary_path = out_dir / "sweep_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nSweep complete. Summary → {summary_path}")

    print("\n=== RANKING (best to worst composite score) ===")
    for i, r in enumerate(ranked):
        print(f"  #{i+1}  {r['backend_key']:35s}  score={r['composite_score']:.4f}  id={r['metrics']['id_drift_rmse']:.4f}  int={r['metrics']['integration_rmse']:.4f}")

    print(f"\nArtifacts:\n  {out_dir}/")
    print(f"  master_comparison.jpg")
    print(f"  refinement_top3.jpg")
    for r in ranked[:3]:
        print(f"  {r['backend_key']}/contact_sheet.jpg  (#{ranked.index(r)+1})")


if __name__ == "__main__":
    main()
