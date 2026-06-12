#!/usr/bin/env python3
"""Build an aspect-preserving before/after review sheet.

This is for small Discord/scoring-sheet artifacts where the reviewer needs to
compare a few stills without any resize distortion. Every panel is letterboxed
into a fixed cell; source pixels are never stretched to fit the cell.

Usage:
  python3 scripts/make_before_after_sheet.py \
      --image raw_a_over_b.png "Raw A-over-B" \
      --image final_comp.png "Latent delta" \
      --out scoring_sheet_before_after.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BG = (18, 20, 24)
PANEL_BG = (28, 31, 38)
TEXT = (232, 235, 240)
DIM = (165, 174, 188)
ACCENT = (117, 189, 255)
PAD = 12
LABEL_H = 28


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _letterbox(path: Path, size: tuple[int, int]) -> tuple[Image.Image, tuple[int, int]]:
    img = Image.open(path).convert("RGB")
    original_size = img.size
    fit = img.copy()
    fit.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, PANEL_BG)
    x = (size[0] - fit.width) // 2
    y = (size[1] - fit.height) // 2
    canvas.paste(fit, (x, y))
    return canvas, original_size


def build(images: list[tuple[Path, str]], out: Path, panel_w: int, panel_h: int, title: str) -> Path:
    if len(images) < 2:
        raise ValueError("at least two --image pairs are required")

    font_title = _font(18)
    font_label = _font(14)
    font_meta = _font(11)

    width = PAD + len(images) * (panel_w + PAD)
    height = PAD + 28 + PAD + LABEL_H + panel_h + PAD + 18 + PAD
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)
    draw.text((PAD, PAD), title, fill=ACCENT, font=font_title)

    y = PAD + 28 + PAD
    for index, (path, label) in enumerate(images):
        x = PAD + index * (panel_w + PAD)
        draw.rectangle((x, y, x + panel_w, y + LABEL_H + panel_h + 18), fill=PANEL_BG)
        draw.text((x + 8, y + 6), label, fill=TEXT, font=font_label)
        panel, original_size = _letterbox(path, (panel_w, panel_h))
        sheet.paste(panel, (x, y + LABEL_H))
        meta = f"{original_size[0]}x{original_size[1]} source, aspect preserved"
        draw.text((x + 8, y + LABEL_H + panel_h + 4), meta, fill=DIM, font=font_meta)

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Make an aspect-preserving before/after sheet")
    parser.add_argument(
        "--image",
        nargs=2,
        action="append",
        metavar=("PATH", "LABEL"),
        required=True,
        help="image path and panel label; repeat for each panel",
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--panel-width", type=int, default=420)
    parser.add_argument("--panel-height", type=int, default=236)
    parser.add_argument("--title", default="Before / after review")
    args = parser.parse_args()

    out = build(
        [(Path(path), label) for path, label in args.image],
        Path(args.out),
        args.panel_width,
        args.panel_height,
        args.title,
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
