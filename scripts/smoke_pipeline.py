#!/usr/bin/env python3
"""Phase 0 smoke pipeline for the latent-merge contract.

This is not the model. It is a deterministic file-flow harness that proves the
V0 IO contract before model work starts:

CG RGBA + plate RGB + alpha -> adjusted foreground + diagnostics -> A-over-B.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = ROOT / "fixtures" / "golden_synthetic_001"
DEFAULT_OUTPUT_DIR = ROOT / "runs" / "phase0_smoke"
FIXTURE_CREATED_UTC = "2026-05-24T22:10:54.851997+00:00"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_rgb(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(array * 255.0, 0, 255).astype(np.uint8)).save(path)


def save_rgba(path: Path, rgb: np.ndarray, alpha: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.dstack((rgb, alpha))
    Image.fromarray(np.clip(rgba * 255.0, 0, 255).astype(np.uint8)).save(path)


def load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def load_rgba(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    return rgba[..., :3], rgba[..., 3:4]


def load_alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)[..., None] / 255.0


def create_fixture(fixture_dir: Path) -> dict[str, str]:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    width, height = 768, 432
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]

    plate = np.zeros((height, width, 3), dtype=np.float32)
    plate[..., 0] = 0.06 + 0.32 * x + 0.08 * y
    plate[..., 1] = 0.08 + 0.24 * x + 0.20 * y
    plate[..., 2] = 0.11 + 0.14 * x + 0.32 * y

    # Add a warm practical light area and darker floor band to give the stub a
    # plausible background color target.
    yy, xx = np.mgrid[0:height, 0:width]
    light = np.exp(-(((xx - 580) / 170) ** 2 + ((yy - 120) / 90) ** 2))
    plate += light[..., None] * np.array([0.55, 0.33, 0.12], dtype=np.float32)
    plate[height // 2 :, :, :] *= np.array([0.55, 0.62, 0.72], dtype=np.float32)

    alpha_img = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha_img)
    draw.ellipse((250, 92, 536, 382), fill=255)
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=4))
    alpha = np.asarray(alpha_img, dtype=np.float32)[..., None] / 255.0

    cg = np.zeros_like(plate)
    cg[..., 0] = 0.18 + 0.18 * y
    cg[..., 1] = 0.42 + 0.08 * x
    cg[..., 2] = 0.82 - 0.18 * y
    highlight = np.exp(-(((xx - 430) / 95) ** 2 + ((yy - 155) / 80) ** 2))
    cg += highlight[..., None] * np.array([0.35, 0.30, 0.18], dtype=np.float32)
    cg = np.clip(cg, 0.0, 1.0)

    plate_path = fixture_dir / "plate_rgb.png"
    cg_path = fixture_dir / "cg_rgba.png"
    alpha_path = fixture_dir / "alpha.png"
    manifest_path = fixture_dir / "fixture.json"

    save_rgb(plate_path, plate)
    save_rgba(cg_path, cg, alpha)
    Image.fromarray(np.clip(alpha[..., 0] * 255.0, 0, 255).astype(np.uint8)).save(alpha_path)

    manifest = {
        "fixture_id": "golden_synthetic_001",
        "plate_provenance": "synthetic",
        "created_utc": FIXTURE_CREATED_UTC,
        "purpose": "Phase 0 deterministic file-flow and regression sentinel; excluded from photographic quality evaluation.",
        "dimensions": [width, height],
        "files": {
            "plate_rgb": plate_path.name,
            "cg_rgba": cg_path.name,
            "alpha": alpha_path.name,
        },
        "color_note": "Synthetic SDR RGB. Full EXR/ACEScg handling is intentionally deferred past Phase 0.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {key: str(fixture_dir / value) for key, value in manifest["files"].items()}


def run_smoke(plate_path: Path, cg_path: Path, alpha_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    plate = load_rgb(plate_path)
    cg_rgb, cg_alpha = load_rgba(cg_path)
    alpha = load_alpha(alpha_path)

    if plate.shape != cg_rgb.shape or alpha.shape[:2] != plate.shape[:2]:
        raise ValueError(
            f"dimension mismatch: plate={plate.shape}, cg={cg_rgb.shape}, alpha={alpha.shape}"
        )

    combined_alpha = np.minimum(alpha, cg_alpha)
    alpha_weight = np.maximum(combined_alpha, 1e-6)
    plate_mean = (plate * combined_alpha).sum(axis=(0, 1)) / alpha_weight.sum()
    cg_mean = (cg_rgb * combined_alpha).sum(axis=(0, 1)) / alpha_weight.sum()

    # Conservative mean-match stub: enough to prove file flow and diagnostics,
    # not enough to count as model progress.
    gain = np.clip(plate_mean / np.maximum(cg_mean, 1e-4), 0.72, 1.28)
    adjusted_rgb = np.clip(cg_rgb * gain[None, None, :], 0.0, 1.0)
    final_comp = adjusted_rgb * combined_alpha + plate * (1.0 - combined_alpha)
    delta = np.abs(adjusted_rgb - cg_rgb)
    alpha_weighted_delta = delta * combined_alpha

    outputs = {
        "adjusted_fg": output_dir / "adjusted_fg.png",
        "final_comp": output_dir / "final_comp.png",
        "delta": output_dir / "delta.png",
        "alpha_weighted_delta": output_dir / "alpha_weighted_delta.png",
        "alpha_used": output_dir / "alpha_used.png",
        "job": output_dir / "job.json",
    }

    save_rgba(outputs["adjusted_fg"], adjusted_rgb, combined_alpha)
    save_rgb(outputs["final_comp"], final_comp)
    save_rgb(outputs["delta"], delta)
    save_rgb(outputs["alpha_weighted_delta"], alpha_weighted_delta)
    Image.fromarray(np.clip(combined_alpha[..., 0] * 255.0, 0, 255).astype(np.uint8)).save(
        outputs["alpha_used"]
    )

    job = {
        "schema": "latent-merge.phase0-smoke.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "plate_rgb": {"path": str(plate_path), "sha256": sha256_file(plate_path)},
            "cg_rgba": {"path": str(cg_path), "sha256": sha256_file(cg_path)},
            "alpha": {"path": str(alpha_path), "sha256": sha256_file(alpha_path)},
        },
        "outputs": {key: str(path) for key, path in outputs.items() if key != "job"},
        "stub_transform": {
            "name": "conservative_alpha_weighted_mean_match",
            "plate_mean_under_alpha": plate_mean.round(6).tolist(),
            "cg_mean_under_alpha": cg_mean.round(6).tolist(),
            "rgb_gain": gain.round(6).tolist(),
        },
        "contract": {
            "plate_repainted": False,
            "primary_model_output": "adjusted foreground RGBA",
            "trusted_composite": "normal A-over-B over original plate",
        },
    }
    outputs["job"].write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return outputs["job"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the latent-merge Phase 0 smoke pipeline.")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--create-fixture", action="store_true")
    parser.add_argument("--plate", type=Path)
    parser.add_argument("--cg", type=Path)
    parser.add_argument("--alpha", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.create_fixture:
        create_fixture(args.fixture_dir)

    plate = args.plate or args.fixture_dir / "plate_rgb.png"
    cg = args.cg or args.fixture_dir / "cg_rgba.png"
    alpha = args.alpha or args.fixture_dir / "alpha.png"

    missing = [str(path) for path in (plate, cg, alpha) if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "missing smoke inputs: " + ", ".join(missing) + "; rerun with --create-fixture"
        )

    job_path = run_smoke(plate, cg, alpha, args.output_dir)
    print(f"wrote {job_path}")


if __name__ == "__main__":
    main()
