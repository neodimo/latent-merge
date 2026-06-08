#!/usr/bin/env python3
"""Render a Phase 2 sequence review video for Discord.

The flicker metric is useful for hard rejection, but temporal consistency still
needs eyes on motion. This script turns a sequence run directory produced by
`scripts/evaluate_sequence_flicker.py` into an MP4 that keeps the same visual
grammar as the still contact sheet:

  plate | CG (over checker) | raw A-over-B | adjusted FG | final comp | delta

Usage:
  PYTHONPATH=".deps:." python3 scripts/phase2_sequence_video.py \
      --sequence-metrics runs/<sequence>/sequence_metrics.json \
      --out runs/<sequence>/sequence_review.mp4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

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
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    mask = ((xx // square) + (yy // square)) % 2 == 0
    arr[mask] = 170
    arr[~mask] = 100
    return Image.fromarray(arr, "RGB")


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
    for candidate in order:
        if candidate.is_file():
            return candidate
    return None


def _pair_lookup(metrics: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for pair in metrics.get("pair_metrics", []):
        to_index = pair.get("to")
        if isinstance(to_index, int):
            out[to_index] = pair
    return out


def _frame_canvas(frame: dict[str, Any], pair: dict[str, Any] | None, thumb: int,
                  title: str) -> Image.Image:
    job_path = Path(frame["job"])
    job_dir = job_path.parent
    job = json.loads(job_path.read_text(encoding="utf-8"))

    tiles: list[Image.Image | None] = []
    for col in COLUMNS:
        kind, key = OUTPUT_KEYS[col]
        if kind == "input":
            entry = job.get("inputs", {}).get(key)
            path = _resolve(entry["path"], job_dir, prefer_local=False) if entry else None
        else:
            entry = job.get("outputs", {}).get(key)
            path = _resolve(entry, job_dir, prefer_local=True) if entry else None
        tiles.append(_load_tile(path, thumb) if path else None)

    tile_h = max((tile.size[1] for tile in tiles if tile), default=thumb)
    cell_w = thumb + PAD
    width = ROWLABEL_W + len(COLUMNS) * cell_w + PAD
    height = HEADER_H + LABEL_H + tile_h + PAD

    canvas = Image.new("RGB", (width, height), (24, 24, 28))
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, 5), title, fill=(235, 235, 235))

    y0 = HEADER_H
    for i, col in enumerate(COLUMNS):
        draw.text((ROWLABEL_W + i * cell_w + PAD, y0), col, fill=(180, 200, 230))

    y = HEADER_H + LABEL_H
    label_lines = [
        f"frame_{int(frame.get('frame', 0)):03d}",
        (Path(frame.get("source", "")).name or job_dir.name),
    ]
    if pair:
        rmse = pair.get("final_comp_temporal_rmse")
        if isinstance(rmse, (int, float)):
            label_lines.append(f"rmse {rmse:.5f}")
    for idx, line in enumerate(label_lines):
        draw.text((PAD, y + idx * 13), line[:24], fill=(220, 220, 220))

    for i, tile in enumerate(tiles):
        x = ROWLABEL_W + i * cell_w + PAD
        if tile is not None:
            canvas.paste(tile, (x, y))
        else:
            draw.rectangle([x, y, x + thumb, y + tile_h], outline=(80, 80, 80))
            draw.text((x + 4, y + 4), "n/a", fill=(120, 120, 120))

    # H.264/yuv420p wants even dimensions.
    even_w = canvas.size[0] + (canvas.size[0] % 2)
    even_h = canvas.size[1] + (canvas.size[1] % 2)
    if (even_w, even_h) != canvas.size:
        padded = Image.new("RGB", (even_w, even_h), (24, 24, 28))
        padded.paste(canvas, (0, 0))
        return padded
    return canvas


def render(metrics_path: Path, out: Path, fps: float, thumb: int, title: str) -> Path:
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    frames = metrics.get("frames", [])
    if not frames:
        raise ValueError(f"{metrics_path} does not list any sequence frames")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to render the Discord-review MP4")

    pair_by_frame = _pair_lookup(metrics)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="phase2_sequence_video_") as tmp:
        frame_dir = Path(tmp)
        for index, frame in enumerate(frames):
            canvas = _frame_canvas(frame, pair_by_frame.get(index), thumb, title)
            canvas.save(frame_dir / f"frame_{index:05d}.png")

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out),
        ]
        subprocess.run(cmd, check=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Discord-viewable Phase 2 sequence MP4.")
    parser.add_argument("--sequence-metrics", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--thumb", type=int, default=320)
    parser.add_argument("--title", default="Phase 2 sequence review")
    args = parser.parse_args()
    out = render(args.sequence_metrics, args.out, args.fps, args.thumb, args.title)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
