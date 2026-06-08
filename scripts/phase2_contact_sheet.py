#!/usr/bin/env python3
"""Phase 2 contact-sheet generator.

Builds a labeled visual grid from one or more pipeline job directories so a
reviewer (or a cron post) can see, per case/backend, the inputs and the
harmonization result side by side. This is the standard still-result visual for
Phase 2 — and the artifact the blind A/B scoring (Layer 2) draws from.

Each row is one job. Columns:
  plate | CG (over checker) | raw A-over-B | adjusted FG (over checker) | final comp | delta

If a job dir has a rejection_checks.json, its PASS/FAIL is stamped on the row.

Usage:
  PYTHONPATH=".deps:." python3 scripts/phase2_contact_sheet.py \
      --job runs/caseA --job runs/caseB \
      --out runs/phase2_contact_sheet.png [--thumb 320] [--title "Phase 2 cases"]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

COLUMNS = ["plate", "CG (rgba)", "raw A-over-B", "adjusted FG", "final comp", "delta"]
OUTPUT_KEYS = {
    "plate": ("input", "plate_rgb"),
    "CG (rgba)": ("input", "cg_rgba"),
    "raw A-over-B": ("output", "raw_a_over_b"),
    "adjusted FG": ("output", "adjusted_fg"),
    "final comp": ("output", "final_comp"),
    "delta": ("output", "delta"),
}
PAD = 6
LABEL_H = 18
HEADER_H = 22
ROWLABEL_W = 150


def _checker(size: tuple[int, int], square: int = 16) -> Image.Image:
    w, h = size
    a = np.zeros((h, w, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    mask = ((xx // square) + (yy // square)) % 2 == 0
    a[mask] = 170
    a[~mask] = 100
    return Image.fromarray(a, "RGB")


def _load_tile(path: Path, thumb: int) -> Image.Image:
    img = Image.open(path)
    if img.mode == "RGBA":
        bg = _checker(img.size)
        bg.paste(img, (0, 0), img)
        img = bg
    else:
        img = img.convert("RGB")
    w, h = img.size
    scale = thumb / max(w, 1)
    return img.resize((thumb, max(1, int(h * scale))), Image.BILINEAR)


def _resolve(path_str: str, job_dir: Path, prefer_local: bool) -> Path | None:
    p = Path(path_str)
    by_name = job_dir / p.name
    order = [by_name, p] if prefer_local else [p, by_name]
    for c in order:
        if c.is_file():
            return c
    return None


def _row_status(job_dir: Path) -> str:
    rc = job_dir / "rejection_checks.json"
    if not rc.is_file():
        return ""
    data = json.loads(rc.read_text(encoding="utf-8"))
    if data.get("trust_contract_violation"):
        return "TRUST-FAIL"
    return "PASS" if data.get("overall_pass") else "FAIL"


def build(job_dirs: list[Path], out: Path, thumb: int, title: str) -> Path:
    rows = []
    for jd in job_dirs:
        jd = jd if jd.is_dir() else jd.parent
        job = json.loads((jd / "job.json").read_text(encoding="utf-8"))
        tiles = []
        for col in COLUMNS:
            kind, key = OUTPUT_KEYS[col]
            if kind == "input":
                entry = job.get("inputs", {}).get(key)
                path = _resolve(entry["path"], jd, prefer_local=False) if entry else None
            else:
                entry = job.get("outputs", {}).get(key)
                path = _resolve(entry, jd, prefer_local=True) if entry else None
            tiles.append(_load_tile(path, thumb) if path else None)
        label = job.get("config", {}).get("backend") or jd.name
        rows.append((f"{label}\n{jd.name}", _row_status(jd), tiles))

    tile_h = max((t.size[1] for _, _, ts in rows for t in ts if t), default=thumb)
    cell_w = thumb + PAD
    cell_h = tile_h + LABEL_H + PAD
    grid_w = ROWLABEL_W + len(COLUMNS) * cell_w + PAD
    grid_h = HEADER_H + LABEL_H + len(rows) * cell_h + PAD

    canvas = Image.new("RGB", (grid_w, grid_h), (24, 24, 28))
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, 5), title, fill=(235, 235, 235))

    y0 = HEADER_H
    for i, col in enumerate(COLUMNS):
        x = ROWLABEL_W + i * cell_w + PAD
        draw.text((x, y0), col, fill=(180, 200, 230))

    y = HEADER_H + LABEL_H
    for label, status, tiles in rows:
        scol = {"PASS": (120, 220, 120), "FAIL": (235, 140, 120),
                "TRUST-FAIL": (240, 90, 90)}.get(status, (200, 200, 200))
        for li, line in enumerate(label.split("\n")):
            draw.text((PAD, y + li * 12), line[:24], fill=(220, 220, 220))
        if status:
            draw.text((PAD, y + 30), status, fill=scol)
        for i, tile in enumerate(tiles):
            x = ROWLABEL_W + i * cell_w + PAD
            if tile is not None:
                canvas.paste(tile, (x, y))
            else:
                draw.rectangle([x, y, x + thumb, y + tile_h], outline=(80, 80, 80))
                draw.text((x + 4, y + 4), "n/a", fill=(120, 120, 120))
        y += cell_h

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 2 contact-sheet generator")
    ap.add_argument("--job", action="append", required=True, help="job dir (repeatable)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--thumb", type=int, default=320)
    ap.add_argument("--title", default="Phase 2 contact sheet")
    args = ap.parse_args()
    out = build([Path(j) for j in args.job], Path(args.out), args.thumb, args.title)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
