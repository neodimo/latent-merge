#!/usr/bin/env python3
"""Create a deterministic short proxy sequence for Phase 2 flicker checks."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "fixtures" / "synthetic_sequence_001"


def _save_rgb(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8)).save(path)


def _save_rgba(path: Path, rgb: np.ndarray, alpha: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.dstack((rgb, alpha))
    Image.fromarray(np.clip(rgba * 255.0, 0, 255).astype(np.uint8)).save(path)


def _frame(width: int, height: int, idx: int, frame_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    yy, xx = np.mgrid[0:height, 0:width]
    t = idx / max(frame_count - 1, 1)

    plate = np.zeros((height, width, 3), dtype=np.float32)
    plate[..., 0] = 0.055 + 0.24 * x + 0.07 * y
    plate[..., 1] = 0.08 + 0.18 * x + 0.18 * y
    plate[..., 2] = 0.12 + 0.10 * x + 0.28 * y
    practical_x = 0.68 * width + np.sin(t * np.pi * 2.0) * 12.0
    practical = np.exp(-(((xx - practical_x) / 95) ** 2 + ((yy - 0.23 * height) / 54) ** 2))
    plate += practical[..., None] * np.array([0.42, 0.26, 0.09], dtype=np.float32)
    plate[int(height * 0.52) :, :, :] *= np.array([0.58, 0.64, 0.76], dtype=np.float32)

    cx = int(width * (0.43 + 0.055 * (t - 0.5)))
    cy = int(height * (0.54 + 0.035 * np.sin(t * np.pi)))
    alpha_img = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha_img)
    draw.ellipse((cx - 62, cy - 82, cx + 66, cy + 76), fill=255)
    draw.rectangle((cx - 18, cy + 48, cx + 30, cy + 100), fill=255)
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=3))
    alpha = np.asarray(alpha_img, dtype=np.float32)[..., None] / 255.0

    cg = np.zeros_like(plate)
    cg[..., 0] = 0.20 + 0.12 * y + 0.03 * np.sin(t * np.pi * 2.0)
    cg[..., 1] = 0.42 + 0.08 * x
    cg[..., 2] = 0.76 - 0.12 * y
    highlight = np.exp(-(((xx - (cx + 28)) / 44) ** 2 + ((yy - (cy - 52)) / 42) ** 2))
    cg += highlight[..., None] * np.array([0.34, 0.30, 0.18], dtype=np.float32)
    cg = np.clip(cg, 0.0, 1.0)
    return plate, cg, alpha


def create_sequence(out_dir: Path, frame_count: int, width: int, height: int) -> Path:
    frames = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(frame_count):
        frame_dir = out_dir / f"frame_{idx:03d}"
        plate, cg, alpha = _frame(width, height, idx, frame_count)
        _save_rgb(frame_dir / "plate_rgb.png", plate)
        _save_rgba(frame_dir / "cg_rgba.png", cg, alpha)
        Image.fromarray(np.clip(alpha[..., 0] * 255.0, 0, 255).astype(np.uint8)).save(frame_dir / "alpha.png")
        frames.append(
            {
                "frame": idx,
                "directory": frame_dir.name,
                "plate_rgb": "plate_rgb.png",
                "cg_rgba": "cg_rgba.png",
                "alpha": "alpha.png",
            }
        )

    manifest = {
        "fixture_id": out_dir.name,
        "schema": "latent-merge.sequence-fixture.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Deterministic short proxy sequence for Phase 2 temporal/flicker checks.",
        "dimensions": [width, height],
        "frame_count": frame_count,
        "color_note": "Synthetic SDR RGB proxy. Not a production-look validation case.",
        "frames": frames,
    }
    manifest_path = out_dir / "sequence.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a deterministic Phase 2 sequence fixture.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--frames", type=int, default=6)
    parser.add_argument("--width", type=int, default=384)
    parser.add_argument("--height", type=int, default=216)
    args = parser.parse_args()
    if args.frames < 2:
        raise ValueError("--frames must be at least 2")
    manifest = create_sequence(args.out_dir, args.frames, args.width, args.height)
    print(f"wrote {manifest}")


if __name__ == "__main__":
    main()
