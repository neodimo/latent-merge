#!/usr/bin/env python3
"""
Speculative IC-Light V2 / FLUX runner for latent-merge.

Status: not verified. This script assumes compatible IC-Light-on-FLUX
ControlNet weights and an official inference recipe are available locally.
Do not use its outputs as Phase 2 evidence until that dependency is proven and
the outputs run on accepted photographic fixtures, pass Layer 1, and beat raw
A-over-B in blind Layer-2 review. See docs/IC_LIGHT_FLUX_STATUS.md.

Requires:
  - CUDA GPU with ≥12 GB VRAM (RTX 3080 Ti or better)
  - torch + CUDA: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
  - pip install diffusers transformers accelerate huggingface_hub xformers

IC-Light V2 conditions FLUX.1-dev on a background plate to harmonize/relight
the foreground CG element. Returns adjusted foreground (A channel preserved) +
a final comp, delta, and job metadata — same output contract as CPU backends.

Usage:
    python3 scripts/ic_flux_runner.py \\
        --plate  fixtures/golden_synthetic_001/plate_rgb.png \\
        --cg     fixtures/golden_synthetic_001/cg_rgba.png  \\
        --alpha  fixtures/golden_synthetic_001/alpha.png    \\
        --seed   42 --steps 20 --cfg 3.5                   \\
        --out-dir runs/overnight_20260530/ic_flux_baseline  \\
        --weights-dir weights/ic-light-v2

Download weights once before running:
    python3 -c "
    from huggingface_hub import snapshot_download
    snapshot_download('lllyasviel/ic-light', local_dir='weights/ic-light-v2')
    snapshot_download('black-forest-labs/FLUX.1-dev', local_dir='weights/flux1-dev')
    "
"""

from __future__ import annotations
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--plate",            type=Path, required=True)
    p.add_argument("--cg",               type=Path, required=True)
    p.add_argument("--alpha",            type=Path, required=True)
    p.add_argument("--seed",             type=int,   default=42)
    p.add_argument("--steps",            type=int,   default=20)
    p.add_argument("--cfg",              type=float, default=3.5)
    p.add_argument("--cond-strength",    type=float, default=0.75, dest="cond_strength")
    p.add_argument("--resolution",       type=int,   default=768,
                   help="Resize shorter side to this before inference (px)")
    p.add_argument("--out-dir",          type=Path,  required=True)
    p.add_argument("--weights-dir",      type=Path,  default=Path("weights/ic-light-v2"))
    p.add_argument("--flux-weights-dir", type=Path,  default=Path("weights/flux1-dev"))
    p.add_argument("--fp16",             action="store_true", default=True,
                   help="Use float16 (saves VRAM, default on)")
    p.add_argument("--no-fp16",          action="store_false", dest="fp16")
    return p.parse_args()


def _check_gpu() -> None:
    try:
        import torch
    except ImportError:
        raise RuntimeError(
            "torch not installed. Run:\n"
            "  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121"
        )
    if not torch.cuda.is_available():
        raise RuntimeError(
            f"CUDA GPU required. torch.cuda.is_available() = False.\n"
            f"Device count: {torch.cuda.device_count()}"
        )
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    print(f"GPU: {torch.cuda.get_device_name(0)}, VRAM: {vram_gb:.1f} GB")
    if vram_gb < 10:
        raise RuntimeError(f"IC-Light V2 FLUX needs ≥12 GB VRAM; found {vram_gb:.1f} GB.")


def _resize_to(img: Image.Image, size: int) -> Image.Image:
    w, h = img.size
    scale = size / min(w, h)
    return img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)


def _load_pipeline(args):
    import torch
    from diffusers import (
        FluxControlNetPipeline,
        FluxControlNetModel,
    )

    dtype = torch.float16 if args.fp16 else torch.float32

    # IC-Light V2 is packaged as a ControlNet adapter on top of FLUX.1-dev.
    # The ControlNet encodes the background plate as the conditioning signal.
    # Weights: lllyasviel/ic-light  (IC-Light V1/V2 unified HF repo as of 2025-H1)
    controlnet = FluxControlNetModel.from_pretrained(
        str(args.weights_dir),
        torch_dtype=dtype,
    )

    pipe = FluxControlNetPipeline.from_pretrained(
        str(args.flux_weights_dir),
        controlnet=controlnet,
        torch_dtype=dtype,
    )
    pipe.enable_model_cpu_offload()          # keeps 12 GB VRAM usage manageable
    try:
        pipe.enable_xformers_memory_efficient_attention()
        print("xformers memory-efficient attention enabled")
    except Exception as error:
        print(f"xformers unavailable; continuing without it: {error}")

    return pipe, dtype


def _run_inference(pipe, args, plate: Image.Image, cg_rgb: Image.Image) -> Image.Image:
    import torch

    generator = torch.Generator(device="cuda").manual_seed(args.seed)

    # IC-Light V2 conditioning: provide the plate as control image.
    # The model harmonizes the subject (cg_rgb) to match the plate's lighting.
    result = pipe(
        prompt="",                          # IC-Light V2 is image-conditioned, no text prompt
        control_image=plate,
        image=cg_rgb,
        num_inference_steps=args.steps,
        guidance_scale=args.cfg,
        controlnet_conditioning_scale=args.cond_strength,
        generator=generator,
        height=plate.height,
        width=plate.width,
    )
    return result.images[0]


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    _check_gpu()

    import torch

    plate_orig = Image.open(args.plate).convert("RGB")
    cg_orig    = Image.open(args.cg).convert("RGBA")
    alpha_orig = cg_orig.getchannel("A")

    # Resize to inference resolution
    plate = _resize_to(plate_orig, args.resolution)
    cg    = _resize_to(cg_orig.convert("RGB"), args.resolution)
    alpha = _resize_to(alpha_orig, args.resolution)

    print(f"Inference resolution: {plate.width}×{plate.height}")
    print(f"Loading IC-Light V2 FLUX pipeline from {args.weights_dir} …")

    t0 = time.perf_counter()
    pipe, dtype = _load_pipeline(args)
    t_load = time.perf_counter() - t0
    print(f"Pipeline loaded in {t_load:.1f}s")

    print(f"Running {args.steps} steps  cfg={args.cfg}  seed={args.seed} …")
    t1 = time.perf_counter()
    adjusted_fg = _run_inference(pipe, args, plate, cg)
    t_infer = time.perf_counter() - t1
    print(f"Inference done in {t_infer:.1f}s")

    # Resize back to original resolution
    adjusted_fg = adjusted_fg.resize(plate_orig.size, Image.LANCZOS)
    alpha_resized = alpha_orig

    # Final comp: adjusted over original plate
    plate_arr = np.asarray(plate_orig, dtype=np.float32) / 255.0
    fg_arr    = np.asarray(adjusted_fg, dtype=np.float32) / 255.0
    cg_arr    = np.asarray(cg_orig.convert("RGB"), dtype=np.float32) / 255.0
    a_arr     = np.asarray(alpha_resized, dtype=np.float32)[..., None] / 255.0

    comp  = fg_arr * a_arr + plate_arr * (1.0 - a_arr)
    delta = np.abs(fg_arr - cg_arr)
    alpha_weighted_delta = delta * a_arr

    adjusted_fg_rgba = Image.fromarray(
        np.concatenate([
            (fg_arr * 255).astype("uint8"),
            np.asarray(alpha_resized)[..., None],
        ], axis=-1)
    )
    adjusted_fg_rgba.save(args.out_dir / "adjusted_fg.png")
    Image.fromarray((comp  * 255).astype("uint8")).save(args.out_dir / "final_comp.png")
    Image.fromarray((delta * 255).astype("uint8")).save(args.out_dir / "delta.png")
    Image.fromarray((alpha_weighted_delta * 255).astype("uint8")).save(
        args.out_dir / "alpha_weighted_delta.png"
    )

    # Metrics (same schema as CPU backends)
    alpha_mask = a_arr[..., 0] > 0.1
    id_drift     = float(np.mean(delta[alpha_mask]))
    integration  = float(np.mean(np.abs(
        fg_arr * a_arr + plate_arr * (1 - a_arr) -
        cg_arr * a_arr + plate_arr * (1 - a_arr)
    )))

    job = {
        "schema": "latent-merge.ic-flux-run.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "backend": "ic_light_v2_flux",
        "hardware": {
            "gpu": torch.cuda.get_device_name(0),
            "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1),
        },
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
            "resolution": args.resolution,
            "fp16": args.fp16,
        },
        "metrics": {
            "id_drift": id_drift,
            "integration": integration,
        },
        "timing": {
            "pipeline_load_s": round(t_load, 2),
            "inference_s": round(t_infer, 2),
        },
        "status": "ok",
        "outputs": {
            "adjusted_fg":            str(args.out_dir / "adjusted_fg.png"),
            "final_comp":             str(args.out_dir / "final_comp.png"),
            "delta":                  str(args.out_dir / "delta.png"),
            "alpha_weighted_delta":   str(args.out_dir / "alpha_weighted_delta.png"),
        },
    }
    (args.out_dir / "job.json").write_text(json.dumps(job, indent=2))
    print(f"\nDone — {args.out_dir}")
    print(f"  id_drift={id_drift:.4f}  integration={integration:.4f}")
    print(f"  total_time={t_load + t_infer:.1f}s")


if __name__ == "__main__":
    main()
