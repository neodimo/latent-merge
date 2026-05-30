#!/usr/bin/env python3
"""
IC-Light V2 / FLUX runner stub for latent-merge.
Run this on hardware with a CUDA GPU (≥12 GB VRAM).
See runs/overnight_20260530/ic_flux_docs.json for install instructions.

Usage:
    python3 scripts/ic_flux_runner.py \
        --plate  fixtures/golden_synthetic_001/plate_rgb.png \
        --cg     fixtures/golden_synthetic_001/cg_rgba.png \
        --alpha  fixtures/golden_synthetic_001/alpha.png \
        --seed   42 --steps 20 --cfg 3.5 \
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
            "torch and diffusers are required. Run:\n"
            "  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121\n"
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
