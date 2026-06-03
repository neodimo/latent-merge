#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def _load_rgba(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    return rgba[..., :3], rgba[..., 3]


def _load_alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def _resolve_job_path(job_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if path.exists():
        return path.resolve()
    return (job_path.parent / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail on degenerate harmonization output.")
    parser.add_argument("--job", type=Path, required=True, help="Path to pipeline job.json")
    parser.add_argument("--cg", type=Path, help="Optional original CG RGBA input for drift checks")
    parser.add_argument("--min-foreground-mean", type=float, default=0.02)
    parser.add_argument("--min-foreground-std", type=float, default=0.005)
    parser.add_argument("--max-identity-delta", type=float, default=0.75)
    parser.add_argument("--min-mask-pixels", type=int, default=32)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    job_path = args.job.resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    outputs = job.get("outputs", {})

    missing = [key for key in ("adjusted_fg", "final_comp", "alpha_used") if key not in outputs]
    if missing:
        raise AssertionError(f"job is missing outputs: {', '.join(missing)}")

    adjusted_rgb, adjusted_alpha = _load_rgba(_resolve_job_path(job_path, outputs["adjusted_fg"]))
    final_rgb = _load_rgb(_resolve_job_path(job_path, outputs["final_comp"]))
    alpha = _load_alpha(_resolve_job_path(job_path, outputs["alpha_used"]))

    if adjusted_rgb.shape[:2] != final_rgb.shape[:2] or alpha.shape != adjusted_rgb.shape[:2]:
        raise AssertionError(
            f"shape mismatch: adjusted={adjusted_rgb.shape}, final={final_rgb.shape}, alpha={alpha.shape}"
        )

    mask = alpha > 0.05
    mask_pixels = int(mask.sum())
    if mask_pixels < args.min_mask_pixels:
        raise AssertionError(f"foreground mask too small: {mask_pixels} pixels")

    fg = adjusted_rgb[mask]
    fg_mean = float(fg.mean())
    fg_std = float(fg.std())
    alpha_mean = float(adjusted_alpha[mask].mean())

    if fg_mean < args.min_foreground_mean:
        raise AssertionError(f"adjusted foreground is near-black: mean={fg_mean:.6f}")
    if fg_std < args.min_foreground_std:
        raise AssertionError(f"adjusted foreground is near-flat: std={fg_std:.6f}")
    if alpha_mean < 0.05:
        raise AssertionError(f"adjusted foreground alpha is near-empty: mean={alpha_mean:.6f}")

    if args.cg is not None:
        cg_rgb, _ = _load_rgba(args.cg)
        if cg_rgb.shape != adjusted_rgb.shape:
            raise AssertionError(f"CG shape mismatch: cg={cg_rgb.shape}, adjusted={adjusted_rgb.shape}")
        identity_delta = float(np.abs(adjusted_rgb[mask] - cg_rgb[mask]).mean())
        if identity_delta > args.max_identity_delta:
            raise AssertionError(f"adjusted foreground drift too high: delta={identity_delta:.6f}")
    else:
        identity_delta = None

    print(
        "harmonization output OK: "
        f"mask_pixels={mask_pixels} fg_mean={fg_mean:.6f} fg_std={fg_std:.6f} "
        f"alpha_mean={alpha_mean:.6f}"
        + ("" if identity_delta is None else f" identity_delta={identity_delta:.6f}")
    )


if __name__ == "__main__":
    main()
