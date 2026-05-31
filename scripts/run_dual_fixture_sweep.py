#!/usr/bin/env python3
"""
Dual-fixture sweep — top techniques on both real-world and synthetic data.
Runs on:
1. compositingpro_sh009_minimal  (1920x1080 — real plate from compositing.pro)
  2. golden_synthetic_001         (768x432   — synthetic control)

Produces labeled contact sheets for each fixture and a cross-fixture comparison sheet.
"""
from pathlib import Path
import json, sys, os
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path("/home/omid/.openclaw/workspace/repos/latent-merge")
sys.path.insert(0, str(ROOT))

DEVICE = "cuda" if __import__("torch").cuda.is_available() else "cpu"
print(f"DEVICE: {DEVICE}")

# ── Fixtures ─────────────────────────────────────────────────────────────────

FIXTURES = {
    "compositingpro_sh009_minimal": Path("/home/omid/.openclaw/workspace/projects/latent-merge/fixtures/compositingpro_sh009_minimal"),
    "golden_synthetic_001":          Path("/home/omid/.openclaw/workspace/repos/latent-merge/fixtures/golden_synthetic_001"),
}

# ── Loaders ──────────────────────────────────────────────────────────────────

def load_rgb(path):
    return np.array(Image.open(path)).astype(np.float32) / 255.0

def load_rgba(path):
    a = np.array(Image.open(path))
    return a[:, :, :3].astype(np.float32) / 255.0, a[:, :, 3].astype(np.float32) / 255.0

def save_rgb(path, arr):
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(path)

def composite(fg, bg, a):
    a3 = a[..., np.newaxis] if a.ndim == 2 else a
    return fg * a3 + bg * (1 - a3)

# ── Techniques (top 4 from overnight sweep) ───────────────────────────────────

def mean_match_stub(plate, cg_rgb, alpha_2d):
    aw = np.maximum(alpha_2d, 1e-6)
    pm = (plate * alpha_2d[..., None]).sum(axis=(0, 1)) / aw.sum()
    cm = (cg_rgb * alpha_2d[..., None]).sum(axis=(0, 1)) / aw.sum()
    gain = np.clip(pm / np.maximum(cm, 1e-4), 0.72, 1.28)
    adjusted = np.clip(cg_rgb * gain[None, None, :], 0.0, 1.0)
    return adjusted, {"name": "mean_match_stub", "gain": gain.round(6).tolist()}

def histogram_transfer(plate, cg_rgb, alpha_2d):
    fg_mask = alpha_2d > 0.1
    adjusted = cg_rgb.copy()
    for c in range(3):
        src = cg_rgb[..., c][fg_mask]
        ref = plate[..., c][fg_mask]
        if len(src) < 10:
            continue
        src_sorted = np.sort(src)
        ref_sorted = np.sort(ref)
        idx = np.clip(np.searchsorted(src_sorted, src), 0, len(ref_sorted) - 1)
        adjusted[..., c][fg_mask] = ref_sorted[idx]
    return np.clip(adjusted, 0, 1), {"name": "histogram_transfer"}

def style_transfer_light(plate, cg_rgb, alpha_2d):
    fg_mask = alpha_2d > 0.1
    adjusted = cg_rgb.copy()
    for c in range(3):
        src = cg_rgb[..., c][fg_mask]
        ref = plate[..., c][fg_mask]
        if len(src) < 10:
            continue
        src_mean, src_std = src.mean(), src.std() + 1e-6
        ref_mean, ref_std = ref.mean(), ref.std() + 1e-6
        adjusted[..., c] = np.clip(
            (cg_rgb[..., c] - src_mean) / src_std * ref_std + ref_mean, 0, 1)
    return np.clip(adjusted, 0, 1), {"name": "style_transfer_light"}

def channel_rebalance(plate, cg_rgb, alpha_2d):
    fg_mask = alpha_2d > 0.1
    adjusted = cg_rgb.copy()
    for c in range(3):
        src_mean = cg_rgb[..., c][fg_mask].mean()
        ref_mean = plate[..., c][fg_mask].mean()
        ratio = ref_mean / max(src_mean, 1e-6)
        adjusted[..., c] = np.clip(cg_rgb[..., c] * ratio, 0, 1)
    return np.clip(adjusted, 0, 1), {"name": "channel_rebalance"}

def pctnet_harmonize(plate, cg_rgb, alpha_2d):
    from models.pctnet.pctnet_harmonizer import PCTNetHarmonizer
    weight_path = ROOT / "models/pctnet" / "PCTNet_CNN.pth"
    harmonizer = PCTNetHarmonizer(str(weight_path), device=DEVICE, tier="compact-8")
    result = harmonizer.harmonize(cg_rgb, alpha_2d)
    return result, {"name": "pctnet", "model_type": "PCTNet", "device": DEVICE, "tier": "compact-8"}

TECHNIQUES = [
    mean_match_stub,
    histogram_transfer,
    style_transfer_light,
    channel_rebalance,
    pctnet_harmonize,
]

# ── Contact sheet builder ──────────────────────────────────────────────────────

def make_contact_sheet(results, plate_rgb, cg_rgb, combined_2d, combined_3d,
 out_path, fixture_label, n_cols=5, thumb_h=192, thumb_w=192):
    header_cols = 3
    n_tech = len(results)
    total_cols = max(header_cols, n_cols)
    n_rows = 1 + (n_tech + total_cols - 1) // total_cols
    sheet_w = total_cols * thumb_w
    sheet_h = n_rows * thumb_h
    sheet = Image.new("RGB", (sheet_w, sheet_h), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)

    def paste(arr, x, y, label, label_color=(220, 220, 0)):
        arr_u8 = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
        thumb = Image.fromarray(arr_u8).resize((thumb_w, thumb_h), Image.LANCZOS)
        sheet.paste(thumb, (x, y))
        draw.text((x + 2, y + 2), label, fill=label_color)

    # Header row
    paste(plate_rgb,                               0, 0, "PLATE")
    paste(composite(cg_rgb, plate_rgb, combined_3d), thumb_w,         0, "CG_before", (200, 200, 0))
    alpha_vis = np.clip(np.stack([combined_2d]*3, axis=-1), 0, 1)
    paste(alpha_vis,2 * thumb_w, 0, "ALPHA", (180, 180, 180))

    # Technique rows
    for i, (name, adj, meta) in enumerate(results):
        col = i % n_cols
        row = 1 + i // n_cols
        x, y = col * thumb_w, row * thumb_h
        final = composite(adj, plate_rgb, combined_3d)
        paste(final, x, y, name, (80, 255, 120))
        sub = str(meta.get("gain", meta.get("tier", "")))[:30]
        draw.text((x + 2, y + 16), sub, fill=(140, 140, 140))

    # Fixture label top-right
    draw.text((sheet_w - 200, 0), fixture_label, fill=(100, 180, 255))
    sheet.save(out_path, quality=92)
    print(f"  → {out_path}")

# ── Per-fixture run ───────────────────────────────────────────────────────────

def run_fixture(fixture_name, fixture_dir, output_dir):
    print(f"\n{'='*60}")
    print(f"Fixture: {fixture_name}")
    print(f"{'='*60}")

    plate_rgb  = load_rgb(fixture_dir / "plate_rgb.png")
    cg_rgb, cg_alpha = load_rgba(fixture_dir / "cg_rgba.png")
    ext_alpha  = np.array(Image.open(fixture_dir / "alpha.png")).astype(np.float32) / 255.0
    combined_2d = np.minimum(ext_alpha, cg_alpha)
    combined_3d = combined_2d[..., np.newaxis]

    print(f"  plate: {plate_rgb.shape}  cg: {cg_rgb.shape}  alpha: {combined_2d.shape}")

    results = []
    for tech_fn in TECHNIQUES:
        name = tech_fn.__name__
        print(f"  Running {name}...", end=" ", flush=True)
        try:
            adjusted, meta = tech_fn(plate_rgb, cg_rgb, combined_2d)
            results.append((name, adjusted, meta))
            run_dir = output_dir / name
            run_dir.mkdir(parents=True, exist_ok=True)
            save_rgb(run_dir / "adjusted_fg.png", adjusted)
            save_rgb(run_dir / "final_comp.png", composite(adjusted, plate_rgb, combined_3d))
            save_rgb(run_dir / "delta.png", np.abs(adjusted - cg_rgb))
            with open(run_dir / "meta.json", "w") as f:
                json.dump(meta, f, indent=2)
            print("OK")
        except Exception as e:
            print(f"FAILED: {e}")

    # Contact sheet
    sheet_path = output_dir / f"contact_sheet_{fixture_name}.png"
    make_contact_sheet(results, plate_rgb, cg_rgb, combined_2d, combined_3d,
                       sheet_path, fixture_label=fixture_name)

    # Scores
    fg_mask = combined_2d > 0.05
    scores = {}
    for name, adj, _ in results:
        fg_delta   = np.abs(adj[fg_mask] - cg_rgb[fg_mask]).mean()
        final = composite(adj, plate_rgb, combined_3d)
        final_std  = final[fg_mask].std()
        mean_err   = np.abs(adj[fg_mask] - plate_rgb[fg_mask]).mean()
        scores[name] = {
            "fg_delta_mean":   round(float(fg_delta), 6),
            "final_std":       round(float(final_std), 6),
            "mean_err_vs_plate": round(float(mean_err), 6),
        }
    with open(output_dir / f"scores_{fixture_name}.json", "w") as f:
        json.dump(scores, f, indent=2)

    return results, scores

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    timestamp = "dual_sweep"
    output_dir = ROOT / "runs" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    all_scores = {}
    for fixture_name, fixture_dir in FIXTURES.items():
        results, scores = run_fixture(fixture_name, fixture_dir, output_dir)
        all_scores[fixture_name] = scores

    # Cross-fixture summary
    with open(output_dir / "scores_all.json", "w") as f:
        json.dump(all_scores, f, indent=2)

    print(f"\n✓ Done → {output_dir}")
    for fname, scores in all_scores.items():
        print(f"\n{fname}:")
        for name, s in scores.items():
            print(f"  {name}: mean_err={s['mean_err_vs_plate']}  final_std={s['final_std']}")

if __name__ == "__main__":
    main()
