#!/usr/bin/env python3
"""
Refinement round: test parameter variations on the top technique candidates.

Tests:
- local_spatial at 2x2, 3x3 (baseline), 4x4 grids
- polynomial_color: linear-only (3 coeffs), quadratic (7 coeffs, default), cross-term (10 coeffs)
- rgb_affine: standard, with soft-edge alpha dilation, clipped [0.85, 1.15]
- ensemble: blend of top techniques

Usage (from repo root):
    PYTHONPATH=".deps:." python3 scripts/refinement_round.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FONT_PATH_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
FONT_PATH_REG  = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")

THUMB_W, THUMB_H = 384, 216
LABEL_H = 36
PAD = 8
META_H = 64
COLS = 2
BG_COLOR  = (14, 16, 20)
TEXT_COLOR = (220, 228, 240)
DIM_COLOR  = (120, 130, 150)
ACCENT_COLOR = (80, 160, 255)
GOOD_COLOR   = (80, 220, 120)
WARN_COLOR   = (255, 200, 60)
BAD_COLOR    = (255, 80, 80)

OUTPUTS_ORDER = [
    ("final_comp",           "Final Comp"),
    ("adjusted_fg",          "Adjusted FG"),
    ("alpha_used",           "Alpha"),
    ("delta",                "Delta"),
    ("alpha_weighted_delta", "Alpha-Weighted Delta"),
]


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


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    p = FONT_PATH_BOLD if bold else FONT_PATH_REG
    if p.exists():
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def local_spatial(plate, cg_rgb, alpha, grid: int) -> tuple[np.ndarray, dict]:
    H, W = plate.shape[:2]
    adjusted = np.zeros_like(cg_rgb)
    tile_reports = []
    for row in range(grid):
        for col in range(grid):
            r0 = row * H // grid; r1 = (row + 1) * H // grid
            c0 = col * W // grid; c1 = (col + 1) * W // grid
            pt = plate[r0:r1, c0:c1]
            cg = cg_rgb[r0:r1, c0:c1]
            al = alpha[r0:r1, c0:c1]
            aw = np.maximum(al, 1e-6)
            total = aw.sum()
            if al.max() < 0.05:
                adjusted[r0:r1, c0:c1] = cg
                tile_reports.append({"tile": [row, col], "skipped": True})
                continue
            pm = (pt * al).sum(axis=(0, 1)) / total
            cm = (cg  * al).sum(axis=(0, 1)) / total
            gain = np.clip(pm / np.maximum(cm, 1e-4), 0.5, 2.0)
            adjusted[r0:r1, c0:c1] = np.clip(cg * gain[None, None, :], 0.0, 1.0)
            tile_reports.append({"tile": [row, col], "gain": gain.tolist()})
    return np.clip(adjusted, 0.0, 1.0), {"grid": f"{grid}x{grid}", "tiles": tile_reports}


def polynomial_color_ncoeff(plate, cg_rgb, alpha, n_terms: int = 7) -> tuple[np.ndarray, dict]:
    """
    n_terms controls the complexity of the color correction:
      3: linear  (1, R, G, B)
      7: quadratic (+ R^2, G^2, B^2)
      10: cross-terms (+ R^2, G^2, B^2, R*G, R*B, G*B)
    """
    mask = (alpha[..., 0] > 0.1).ravel()
    n = mask.sum()
    if n < 12:
        return _fallback_mean(plate, cg_rgb, alpha)

    R = cg_rgb[..., 0].ravel()[mask]
    G = cg_rgb[..., 1].ravel()[mask]
    B = cg_rgb[..., 2].ravel()[mask]

    if n_terms == 3:
        X = np.stack([np.ones_like(R), R, G, B], axis=1)
        n_reg = 4
    elif n_terms == 7:
        X = np.stack([np.ones_like(R), R, G, B, R*R, G*G, B*B], axis=1)
        n_reg = 7
    elif n_terms == 10:
        X = np.stack([np.ones_like(R), R, G, B, R*R, G*G, B*B, R*G, R*B, G*B], axis=1)
        n_reg = 10
    else:
        raise ValueError(f"Unknown n_terms: {n_terms}")

    adjusted = np.zeros_like(cg_rgb)
    coeffs_all = []

    R_f = cg_rgb[..., 0]; G_f = cg_rgb[..., 1]; B_f = cg_rgb[..., 2]

    for c in range(3):
        y = plate[..., c].ravel()[mask]
        A = X.T @ X + 1e-4 * np.eye(n_reg)
        bv = X.T @ y
        try:
            coeff = np.linalg.solve(A, bv)
        except np.linalg.LinAlgError:
            coeff = np.zeros(n_reg)
            coeff[c + 1] = 1.0

        if n_terms == 3:
            out = coeff[0] + coeff[1]*R_f + coeff[2]*G_f + coeff[3]*B_f
        elif n_terms == 7:
            out = (coeff[0] + coeff[1]*R_f + coeff[2]*G_f + coeff[3]*B_f
                   + coeff[4]*R_f**2 + coeff[5]*G_f**2 + coeff[6]*B_f**2)
        elif n_terms == 10:
            out = (coeff[0] + coeff[1]*R_f + coeff[2]*G_f + coeff[3]*B_f
                   + coeff[4]*R_f**2 + coeff[5]*G_f**2 + coeff[6]*B_f**2
                   + coeff[7]*R_f*G_f + coeff[8]*R_f*B_f + coeff[9]*G_f*B_f)

        adjusted[..., c] = np.clip(out, 0.0, 1.0)
        coeffs_all.append(coeff.tolist())

    return adjusted, {"method": f"polynomial_{n_terms}term", "coefficients_rgb": coeffs_all}


def _fallback_mean(plate, cg_rgb, alpha) -> tuple[np.ndarray, dict]:
    aw = np.maximum(alpha, 1e-6)
    pm = (plate  * alpha).sum(axis=(0, 1)) / aw.sum()
    cm = (cg_rgb * alpha).sum(axis=(0, 1)) / aw.sum()
    gain = np.clip(pm / np.maximum(cm, 1e-4), 0.72, 1.28)
    return np.clip(cg_rgb * gain[None, None, :], 0.0, 1.0), {"gain": gain.tolist()}


def rgb_affine_soft(plate, cg_rgb, alpha, soft_dilate: bool = False,
                    gain_clamp: tuple | None = None) -> tuple[np.ndarray, dict]:
    """RGB affine with optional soft alpha dilation and gain clamping."""
    work_alpha = alpha
    if soft_dilate:
        # Erode alpha slightly to reduce edge contamination
        from PIL import ImageFilter
        alpha_img = Image.fromarray(np.clip(alpha[..., 0] * 255, 0, 255).astype(np.uint8))
        alpha_img = alpha_img.filter(ImageFilter.MinFilter(3))
        work_alpha = np.asarray(alpha_img, dtype=np.float32)[..., None] / 255.0

    aw = np.maximum(work_alpha, 1e-6)
    total = aw.sum()
    pm = (plate  * work_alpha).sum(axis=(0, 1)) / total
    cm = (cg_rgb * work_alpha).sum(axis=(0, 1)) / total
    ps = np.sqrt(((plate  - pm[None, None, :]) ** 2 * work_alpha).sum(axis=(0, 1)) / total + 1e-8)
    cs = np.sqrt(((cg_rgb - cm[None, None, :]) ** 2 * work_alpha).sum(axis=(0, 1)) / total + 1e-8)

    scale = ps / np.maximum(cs, 1e-6)
    if gain_clamp is not None:
        scale = np.clip(scale, gain_clamp[0], gain_clamp[1])

    adjusted = (cg_rgb - cm[None, None, :]) * scale[None, None, :] + pm[None, None, :]
    return np.clip(adjusted, 0.0, 1.0), {
        "scale": scale.tolist(), "soft_dilate": soft_dilate, "gain_clamp": gain_clamp,
    }


def ensemble_top3(plate, cg_rgb, alpha) -> tuple[np.ndarray, dict]:
    """Weighted blend: polynomial (50%) + local_spatial_3x3 (30%) + rgb_affine (20%)."""
    poly, _ = polynomial_color_ncoeff(plate, cg_rgb, alpha, n_terms=7)
    spatial, _ = local_spatial(plate, cg_rgb, alpha, grid=3)
    affine, _ = rgb_affine_soft(plate, cg_rgb, alpha)
    blended = 0.5 * poly + 0.3 * spatial + 0.2 * affine
    return np.clip(blended, 0.0, 1.0), {"blend_weights": {"polynomial": 0.5, "local_spatial": 0.3, "rgb_affine": 0.2}}


REFINEMENT_BACKENDS: dict[str, dict] = {
    "R01_local_2x2": {
        "fn": lambda p, cg, a: local_spatial(p, cg, a, grid=2),
        "label": "R1. Local Spatial 2×2",
        "desc": "Larger tiles, less spatial overfitting",
    },
    "R02_local_3x3": {
        "fn": lambda p, cg, a: local_spatial(p, cg, a, grid=3),
        "label": "R2. Local Spatial 3×3 (sweep best)",
        "desc": "Same as sweep #2",
    },
    "R03_local_4x4": {
        "fn": lambda p, cg, a: local_spatial(p, cg, a, grid=4),
        "label": "R3. Local Spatial 4×4",
        "desc": "Finer tiles, more spatial adaptation",
    },
    "R04_poly_linear": {
        "fn": lambda p, cg, a: polynomial_color_ncoeff(p, cg, a, n_terms=3),
        "label": "R4. Poly Linear (3-term)",
        "desc": "Linear color matrix only (simpler)",
    },
    "R05_poly_quad": {
        "fn": lambda p, cg, a: polynomial_color_ncoeff(p, cg, a, n_terms=7),
        "label": "R5. Poly Quadratic (7-term, sweep best)",
        "desc": "Quadratic features — sweep #1",
    },
    "R06_poly_cross": {
        "fn": lambda p, cg, a: polynomial_color_ncoeff(p, cg, a, n_terms=10),
        "label": "R6. Poly Cross-term (10-term)",
        "desc": "+ cross-terms R*G, R*B, G*B",
    },
    "R07_affine_standard": {
        "fn": lambda p, cg, a: rgb_affine_soft(p, cg, a, soft_dilate=False),
        "label": "R7. RGB Affine (sweep #3)",
        "desc": "Standard mean+std affine",
    },
    "R08_affine_soft_edge": {
        "fn": lambda p, cg, a: rgb_affine_soft(p, cg, a, soft_dilate=True),
        "label": "R8. RGB Affine + Soft Edge",
        "desc": "Alpha-eroded edge masking to reduce halo",
    },
    "R09_affine_clamped": {
        "fn": lambda p, cg, a: rgb_affine_soft(p, cg, a, soft_dilate=False, gain_clamp=(0.85, 1.15)),
        "label": "R9. RGB Affine Clamped [0.85,1.15]",
        "desc": "Conservative std scale clamp",
    },
    "R10_ensemble": {
        "fn": ensemble_top3,
        "label": "R10. Ensemble (Poly+Spatial+Affine)",
        "desc": "50% poly + 30% spatial + 20% affine blend",
    },
}


# ---------------------------------------------------------------------------
# Metrics / contact sheet (same as sweep)
# ---------------------------------------------------------------------------

def compute_metrics(plate, cg_rgb, adjusted, alpha) -> dict[str, float]:
    n = (alpha[..., 0] > 0.1).sum() + 1e-6
    id_drift   = float(np.sqrt(((adjusted - cg_rgb) ** 2 * alpha).sum() / (n * 3)))
    integration = float(np.sqrt(((adjusted - plate)  ** 2 * alpha).sum() / (n * 3)))
    aw_delta   = float(np.abs((adjusted - cg_rgb) * alpha).mean())
    mask = alpha[..., 0] > 0.1
    cg_std  = float(cg_rgb[mask].std()) if mask.sum() > 1 else 1.0
    adj_std = float(adjusted[mask].std()) if mask.sum() > 1 else 1.0
    contrast_ratio = adj_std / max(cg_std, 1e-6)
    fc = adjusted * alpha + plate * (1.0 - alpha)
    plate_repaint_err = float(np.abs(fc * (1.0 - alpha) - plate * (1.0 - alpha)).max())
    return {
        "id_drift_rmse": round(id_drift, 6),
        "integration_rmse": round(integration, 6),
        "aw_delta_mean": round(aw_delta, 6),
        "contrast_ratio": round(contrast_ratio, 4),
        "plate_repaint_err": round(plate_repaint_err, 8),
    }


def _render_contact_sheet(job_dir, outputs, label, desc, metrics, duration_s, backend_key) -> Path:
    font_body   = _load_font(14)
    font_bold   = _load_font(15, bold=True)
    font_tiny   = _load_font(11)
    font_header = _load_font(16, bold=True)

    thumbs = []
    for key, lbl in OUTPUTS_ORDER:
        path = outputs.get(key)
        if path and Path(path).exists():
            img = Image.open(path).convert("RGB")
            thumbs.append((lbl, _letterbox(img, THUMB_W, THUMB_H)))

    ncols = COLS
    nrows = (len(thumbs) + ncols - 1) // ncols
    cell_w = THUMB_W + PAD * 2
    cell_h = THUMB_H + LABEL_H + PAD * 2
    sheet_w = cell_w * ncols + PAD
    sheet_h = META_H + cell_h * nrows + PAD + 80

    sheet = Image.new("RGB", (sheet_w, sheet_h), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    draw.rectangle([(0, 0), (sheet_w, META_H)], fill=(22, 26, 36))
    draw.text((PAD, PAD), label, fill=ACCENT_COLOR, font=font_header)
    draw.text((PAD, PAD + 22), desc, fill=DIM_COLOR, font=font_body)
    draw.text((sheet_w - 200, PAD), backend_key, fill=DIM_COLOR, font=font_tiny)
    draw.text((sheet_w - 200, PAD + 14), f"{duration_s:.2f}s", fill=DIM_COLOR, font=font_tiny)

    for idx, (lbl, img) in enumerate(thumbs):
        col = idx % ncols
        row = idx // ncols
        x = col * cell_w + PAD
        y = META_H + row * cell_h + PAD
        draw.rectangle([(x, y), (x + THUMB_W + PAD, y + THUMB_H + LABEL_H + PAD)], fill=(22, 26, 36))
        draw.text((x + 6, y + 4), lbl, fill=TEXT_COLOR, font=font_bold)
        # img is already letterboxed to THUMB_W × THUMB_H
        sheet.paste(img, (x + 4, y + LABEL_H))

    my = META_H + nrows * cell_h + PAD * 2
    draw.rectangle([(0, my - 4), (sheet_w, sheet_h)], fill=(18, 22, 30))
    mx = PAD
    for text, color in [
        (f"id_drift={metrics['id_drift_rmse']:.4f}",
         GOOD_COLOR if metrics["id_drift_rmse"] < 0.04 else (WARN_COLOR if metrics["id_drift_rmse"] < 0.10 else BAD_COLOR)),
        (f"  integration={metrics['integration_rmse']:.4f}",
         GOOD_COLOR if metrics["integration_rmse"] < 0.08 else (WARN_COLOR if metrics["integration_rmse"] < 0.15 else BAD_COLOR)),
        (f"  contrast={metrics['contrast_ratio']:.3f}", TEXT_COLOR),
        (f"  plate_clean={'YES' if metrics['plate_repaint_err'] < 1e-5 else 'NO'}",
         GOOD_COLOR if metrics["plate_repaint_err"] < 1e-5 else BAD_COLOR),
    ]:
        draw.text((mx, my + 4), text, fill=color, font=font_body)
        bbox = draw.textbbox((mx, my + 4), text, font=font_body)
        mx = bbox[2] + 2

    out_path = job_dir / "contact_sheet.jpg"
    sheet.save(out_path, quality=94)
    return out_path


def _render_refinement_master(runs, out_path) -> None:
    """All refinement runs in one grid sheet."""
    font_body   = _load_font(12)
    font_bold   = _load_font(13, bold=True)
    font_header = _load_font(15, bold=True)
    font_tiny   = _load_font(10)

    TW, TH = 320, 180
    ROW_H = TH + 20
    LABEL_COL_W = 250
    METRIC_COL_W = 340
    SHEET_W = LABEL_COL_W + TW + PAD * 3 + METRIC_COL_W
    HEADER_H = 48

    sheet_h = HEADER_H + len(runs) * ROW_H + PAD * 2
    sheet = Image.new("RGB", (SHEET_W, sheet_h), BG_COLOR)
    draw = ImageDraw.Draw(sheet)

    draw.rectangle([(0, 0), (SHEET_W, HEADER_H)], fill=(22, 26, 36))
    draw.text((PAD, PAD), "Refinement Round — All Variants", fill=ACCENT_COLOR, font=font_header)
    draw.text((PAD, HEADER_H - 14), f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
              fill=DIM_COLOR, font=font_tiny)

    cy = HEADER_H
    for i, run in enumerate(runs):
        m = run["metrics"]
        row_y = cy
        score = run.get("composite_score", 0)

        score_color = GOOD_COLOR if score < 0.15 else (WARN_COLOR if score < 0.18 else BAD_COLOR)

        draw.rectangle([(0, row_y), (LABEL_COL_W, row_y + ROW_H)], fill=(18, 22, 30))
        draw.text((PAD, row_y + 4), run["label"], fill=TEXT_COLOR, font=font_bold)
        draw.text((PAD, row_y + 22), run.get("desc", ""), fill=DIM_COLOR, font=font_tiny)
        draw.text((PAD, row_y + 36), f"score={score:.4f}  rank=#{i+1}", fill=score_color, font=font_tiny)
        draw.text((PAD, row_y + 50), f"t={run.get('duration_s',0):.2f}s", fill=DIM_COLOR, font=font_tiny)

        tx = LABEL_COL_W + PAD
        fp = run.get("final_comp_path")
        if fp and Path(fp).exists():
            img = Image.open(fp).convert("RGB")
            sheet.paste(_letterbox(img, TW, TH), (tx, row_y + 4))

        mx = LABEL_COL_W + TW + PAD * 2
        my = row_y + 4
        draw.text((mx, my),      f"id_drift   {m['id_drift_rmse']:.5f}",
                  fill=GOOD_COLOR if m['id_drift_rmse'] < 0.04 else WARN_COLOR, font=font_body)
        draw.text((mx, my + 16), f"integr.    {m['integration_rmse']:.5f}",
                  fill=GOOD_COLOR if m['integration_rmse'] < 0.08 else WARN_COLOR, font=font_body)
        draw.text((mx, my + 32), f"contrast   {m['contrast_ratio']:.4f}", fill=TEXT_COLOR, font=font_body)
        draw.text((mx, my + 48), f"aw_delta   {m['aw_delta_mean']:.5f}", fill=DIM_COLOR, font=font_body)
        draw.text((mx, my + 64), f"plate_ok   {'YES' if m['plate_repaint_err'] < 1e-5 else 'NO'}",
                  fill=GOOD_COLOR if m['plate_repaint_err'] < 1e-5 else BAD_COLOR, font=font_body)

        cy += ROW_H
        draw.line([(0, cy), (SHEET_W, cy)], fill=(30, 34, 44), width=1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out_path), quality=94)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", type=Path, default=ROOT / "fixtures" / "golden_synthetic_001")
    parser.add_argument("--out-dir",     type=Path, default=ROOT / "runs" / "overnight_20260530" / "refinement")
    args = parser.parse_args()

    fixture_dir = args.fixture_dir
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    plate_path = fixture_dir / "plate_rgb.png"
    cg_path    = fixture_dir / "cg_rgba.png"
    alpha_path = fixture_dir / "alpha.png"

    plate    = load_rgb(plate_path)
    cg_rgb, cg_alpha = load_rgba(cg_path)
    ext_alpha = load_alpha(alpha_path)
    combined_alpha = np.minimum(ext_alpha, cg_alpha)

    run_records = []

    print(f"Running {len(REFINEMENT_BACKENDS)} refinement variants...")

    for bk, bd in REFINEMENT_BACKENDS.items():
        run_dir = out_dir / bk
        run_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [{bk}] {bd['label']}")
        t0 = time.perf_counter()

        try:
            adjusted, report = bd["fn"](plate, cg_rgb, combined_alpha)
        except Exception as exc:
            print(f"    ERROR: {exc}")
            run_records.append({"backend_key": bk, "label": bd["label"], "desc": bd["desc"],
                                  "status": "error", "error": str(exc)})
            continue

        final_comp = adjusted * combined_alpha + plate * (1.0 - combined_alpha)
        delta = np.abs(adjusted - cg_rgb)
        aw_delta = delta * combined_alpha

        outputs = {
            "adjusted_fg":          run_dir / "adjusted_fg.png",
            "final_comp":           run_dir / "final_comp.png",
            "delta":                run_dir / "delta.png",
            "alpha_weighted_delta": run_dir / "alpha_weighted_delta.png",
            "alpha_used":           run_dir / "alpha_used.png",
        }
        save_rgba_img(outputs["adjusted_fg"], adjusted, combined_alpha)
        save_rgb(outputs["final_comp"], final_comp)
        save_rgb(outputs["delta"], delta)
        save_rgb(outputs["alpha_weighted_delta"], aw_delta)
        save_alpha_img(outputs["alpha_used"], combined_alpha)

        metrics = compute_metrics(plate, cg_rgb, adjusted, combined_alpha)
        duration = time.perf_counter() - t0

        cs_path = _render_contact_sheet(
            run_dir, {k: str(v) for k, v in outputs.items()},
            bd["label"], bd["desc"], metrics, duration, bk,
        )

        job = {
            "schema": "latent-merge.refinement-run.v1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "backend_key": bk,
            "label": bd["label"],
            "desc": bd["desc"],
            "fixture": str(fixture_dir),
            "outputs": {k: str(v) for k, v in outputs.items()},
            "contact_sheet": str(cs_path),
            "backend_report": report,
            "metrics": metrics,
            "duration_s": round(duration, 4),
        }
        (run_dir / "job.json").write_text(json.dumps(job, indent=2) + "\n")

        print(f"    id_drift={metrics['id_drift_rmse']:.4f}  integration={metrics['integration_rmse']:.4f}  t={duration:.3f}s")

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

    ok_runs = [r for r in run_records if r.get("status") == "ok"]
    for r in ok_runs:
        m = r["metrics"]
        r["composite_score"] = m["id_drift_rmse"] * 0.4 + m["integration_rmse"] * 0.6

    ranked = sorted(ok_runs, key=lambda r: r["composite_score"])

    master_path = out_dir / "refinement_master.jpg"
    print(f"\nBuilding refinement master sheet → {master_path}")
    _render_refinement_master(ranked, master_path)

    summary = {
        "schema": "latent-merge.refinement-sweep.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "fixture": str(fixture_dir),
        "variants_run": len(ok_runs),
        "master_sheet": str(master_path),
        "ranking": [
            {
                "rank": i + 1,
                "backend_key": r["backend_key"],
                "label": r["label"],
                "composite_score": round(r["composite_score"], 6),
                "metrics": r["metrics"],
                "duration_s": r["duration_s"],
            }
            for i, r in enumerate(ranked)
        ],
    }
    (out_dir / "refinement_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print("\n=== REFINEMENT RANKING ===")
    for i, r in enumerate(ranked):
        print(f"  #{i+1}  {r['backend_key']:35s}  score={r['composite_score']:.4f}  "
              f"id={r['metrics']['id_drift_rmse']:.4f}  int={r['metrics']['integration_rmse']:.4f}")

    print(f"\nArtifacts in: {out_dir}")
    print(f"  refinement_master.jpg")
    for r in ranked[:3]:
        print(f"  {r['backend_key']}/contact_sheet.jpg  (rank #{ranked.index(r)+1})")


if __name__ == "__main__":
    main()
