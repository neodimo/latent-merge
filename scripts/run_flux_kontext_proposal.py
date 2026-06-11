#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.image_io import load_alpha, load_rgb, load_rgba, save_rgb, sha256_file

DEFAULT_PROMPT = (
    "Relight only the inserted foreground object so it matches the plate lighting. "
    "Preserve the object's shape, silhouette, identity, material, texture, and camera angle. "
    "Preserve the background plate. Add only subtle integration cues and plausible contact shadow."
)
DEFAULT_MODEL_ID = "black-forest-labs/FLUX.1-Kontext-dev"
DEFAULT_OUTPUT_DIR = ROOT / "runs" / "flux_kontext_proposal"


def _hf_token() -> str | None:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        return token.strip()
    token_file = Path.home() / ".openclaw" / "secrets" / "hf_token"
    if token_file.is_file():
        value = token_file.read_text(encoding="utf-8").strip()
        return value or None
    return None


def _resize_for_model(rgb: np.ndarray, resolution: int) -> Image.Image:
    image = Image.fromarray(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), mode="RGB")
    image.thumbnail((resolution, resolution), Image.Resampling.LANCZOS)
    # FLUX Kontext is happiest with dimensions divisible by 16.
    width = max(16, image.width - image.width % 16)
    height = max(16, image.height - image.height % 16)
    if (width, height) != image.size:
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image


def _load_pipeline(args: argparse.Namespace):
    import torch
    from diffusers import FluxKontextPipeline

    model_ref = args.model_dir or args.model_id
    dtype = torch.bfloat16 if args.dtype == "bf16" else torch.float16 if args.dtype == "fp16" else torch.float32
    kwargs: dict[str, Any] = {
        "torch_dtype": dtype,
        "token": _hf_token(),
    }
    if args.device_map:
        kwargs["device_map"] = args.device_map
    pipe = FluxKontextPipeline.from_pretrained(model_ref, **kwargs)
    if not args.device_map:
        pipe.to(args.device)
    if args.cpu_offload:
        pipe.enable_model_cpu_offload()
    if args.vae_tiling and hasattr(pipe, "vae"):
        pipe.vae.enable_tiling()
    if args.vae_slicing and hasattr(pipe, "vae"):
        pipe.vae.enable_slicing()
    return pipe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a FLUX Kontext proposal composite for Latent Delta.")
    parser.add_argument("--plate", type=Path, required=True)
    parser.add_argument("--cg", type=Path, required=True)
    parser.add_argument("--alpha", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default="")
    parser.add_argument("--model-id", default=os.environ.get("LATENT_MERGE_FLUX_KONTEXT_REPO", DEFAULT_MODEL_ID))
    parser.add_argument("--model-dir", type=Path, default=os.environ.get("LATENT_MERGE_FLUX_KONTEXT_WEIGHTS") or None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--guidance-scale", type=float, default=2.5)
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--device-map", default="", help="Optional diffusers device_map, e.g. balanced.")
    parser.add_argument("--dtype", choices=("bf16", "fp16", "fp32"), default="bf16")
    parser.add_argument("--cpu-offload", action="store_true")
    parser.add_argument("--vae-tiling", action="store_true", default=True)
    parser.add_argument("--no-vae-tiling", dest="vae_tiling", action="store_false")
    parser.add_argument("--vae-slicing", action="store_true", default=True)
    parser.add_argument("--no-vae-slicing", dest="vae_slicing", action="store_false")
    parser.add_argument("--check-runtime", action="store_true", help="Validate imports/CUDA/model ref, then exit before inference.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    missing = [str(path) for path in (args.plate, args.cg, args.alpha) if not path.exists()]
    if missing:
        raise FileNotFoundError("missing inputs: " + ", ".join(missing))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    plate = load_rgb(args.plate)
    cg_rgb, cg_alpha = load_rgba(args.cg)
    alpha = np.minimum(load_alpha(args.alpha), cg_alpha)
    if plate.shape != cg_rgb.shape or alpha.shape[:2] != plate.shape[:2]:
        raise ValueError(f"dimension mismatch: plate={plate.shape}, cg={cg_rgb.shape}, alpha={alpha.shape}")

    raw_a_over_b = cg_rgb * alpha + plate * (1.0 - alpha)
    input_image = _resize_for_model(raw_a_over_b, args.resolution)
    input_path = args.out_dir / "kontext_input.png"
    save_rgb(input_path, np.asarray(input_image, dtype=np.float32) / 255.0)

    pipe = _load_pipeline(args)
    if args.check_runtime:
        print("FLUX Kontext runtime OK")
        return

    import torch

    generator = torch.Generator(device=args.device if args.device != "cpu" else "cpu").manual_seed(args.seed)
    call_kwargs: dict[str, Any] = {
        "image": input_image,
        "prompt": args.prompt,
        "guidance_scale": args.guidance_scale,
        "num_inference_steps": args.steps,
        "generator": generator,
    }
    if args.negative_prompt:
        call_kwargs["negative_prompt"] = args.negative_prompt
    result = pipe(**call_kwargs)
    proposal_image = result.images[0].convert("RGB").resize((plate.shape[1], plate.shape[0]), Image.Resampling.LANCZOS)
    proposal = np.asarray(proposal_image, dtype=np.float32) / 255.0

    proposal_path = args.out_dir / "proposal.png"
    save_rgb(proposal_path, proposal)
    save_rgb(args.out_dir / "raw_a_over_b.png", raw_a_over_b)

    job = {
        "schema": "latent-merge.flux-kontext-proposal.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "model": {
            "id": args.model_id,
            "dir": str(args.model_dir) if args.model_dir else "",
            "kind": "FLUX.1 Kontext image-edit proposal",
            "source_role": "proposal_only_not_final_pixels",
        },
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "settings": {
            "seed": args.seed,
            "steps": args.steps,
            "guidance_scale": args.guidance_scale,
            "resolution": args.resolution,
            "device": args.device,
            "device_map": args.device_map,
            "dtype": args.dtype,
            "cpu_offload": args.cpu_offload,
            "vae_tiling": args.vae_tiling,
            "vae_slicing": args.vae_slicing,
        },
        "inputs": {
            "plate_rgb": {"path": str(args.plate), "sha256": sha256_file(args.plate)},
            "cg_rgba": {"path": str(args.cg), "sha256": sha256_file(args.cg)},
            "alpha": {"path": str(args.alpha), "sha256": sha256_file(args.alpha)},
        },
        "outputs": {
            "kontext_input": str(input_path),
            "raw_a_over_b": str(args.out_dir / "raw_a_over_b.png"),
            "proposal": str(proposal_path),
        },
        "runtime": {
            "duration_s": round(time.perf_counter() - t0, 4),
        },
        "contract": {
            "proposal_is_final_comp": False,
            "intended_consumer": "cli/run_latent_delta.py --proposal",
            "plate_pixels_trusted": False,
        },
    }
    (args.out_dir / "proposal_job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {proposal_path}")


if __name__ == "__main__":
    main()
