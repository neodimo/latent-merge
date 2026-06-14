#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = ROOT / "fixtures" / "golden_synthetic_001"
DEFAULT_OUTPUT_DIR = ROOT / "runs" / "latent_delta_proxy"
DEFAULT_CONFIG = ROOT / "configs" / "phase1_latent_delta_proxy.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTORCH_JIT", "0")

from core.pipeline import PipelineInputs, load_config, run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Latent Merge constrained proposal/delta workflow. "
            "This keeps the normal trusted output family while adding proposal, lighting-delta, and shadow-preview artifacts."
        )
    )
    parser.add_argument("--plate", type=Path, default=DEFAULT_FIXTURE_DIR / "plate_rgb.png")
    parser.add_argument("--cg", type=Path, default=DEFAULT_FIXTURE_DIR / "cg_rgba.png")
    parser.add_argument("--alpha", type=Path, default=DEFAULT_FIXTURE_DIR / "alpha.png")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--proposal",
        type=Path,
        default=None,
        help="Optional RGB proposal composite from FLUX/other model. If omitted, uses the local deterministic proxy.",
    )
    parser.add_argument("--delta-blur", type=float, default=None, help="Low-frequency blur radius for proposal delta extraction.")
    parser.add_argument("--luma-strength", type=float, default=None, help="Foreground luma delta strength.")
    parser.add_argument("--color-strength", type=float, default=None, help="Foreground color delta strength.")
    parser.add_argument(
        "--kontext-proposal",
        action="store_true",
        help="Generate a FLUX Kontext proposal first, then feed proposal.png into Latent Delta.",
    )
    parser.add_argument("--kontext-python", default=sys.executable, help="Python executable for scripts/run_flux_kontext_proposal.py.")
    parser.add_argument("--kontext-model-dir", type=Path, default=None, help="Optional local FLUX.1-Kontext-dev model directory.")
    parser.add_argument("--kontext-model-id", default="black-forest-labs/FLUX.1-Kontext-dev")
    parser.add_argument("--kontext-prompt", default=None, help="Override the default relighting/edit instruction.")
    parser.add_argument("--kontext-seed", type=int, default=42)
    parser.add_argument("--kontext-steps", type=int, default=24)
    parser.add_argument("--kontext-guidance-scale", type=float, default=2.5)
    parser.add_argument("--kontext-resolution", type=int, default=1024)
    parser.add_argument("--kontext-cpu-offload", action="store_true")
    parser.add_argument("--kontext-device-map", default="", help="Optional Diffusers/Accelerate device_map, e.g. balanced.")
    return parser.parse_args()


def _run_kontext_proposal(args: argparse.Namespace) -> Path:
    proposal_dir = args.output_dir / "flux_kontext_proposal"
    runner = ROOT / "scripts" / "run_flux_kontext_proposal.py"
    command = [
        args.kontext_python,
        str(runner),
        "--plate",
        str(args.plate),
        "--cg",
        str(args.cg),
        "--alpha",
        str(args.alpha),
        "--out-dir",
        str(proposal_dir),
        "--model-id",
        args.kontext_model_id,
        "--seed",
        str(args.kontext_seed),
        "--steps",
        str(args.kontext_steps),
        "--guidance-scale",
        str(args.kontext_guidance_scale),
        "--resolution",
        str(args.kontext_resolution),
    ]
    if args.kontext_model_dir:
        command.extend(["--model-dir", str(args.kontext_model_dir)])
    if args.kontext_prompt:
        command.extend(["--prompt", args.kontext_prompt])
    if args.kontext_cpu_offload:
        command.append("--cpu-offload")
    if args.kontext_device_map:
        command.extend(["--device-map", args.kontext_device_map])
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            "FLUX Kontext proposal generation failed. "
            "This is the real proposal-model step, not the local proxy. "
            "Check model access/weights, CUDA memory, and diffusers version."
        ) from error
    proposal = proposal_dir / "proposal.png"
    if not proposal.is_file():
        raise RuntimeError(f"FLUX Kontext runner completed without {proposal}")
    return proposal


def main() -> None:
    args = parse_args()
    if args.proposal and args.kontext_proposal:
        raise ValueError("use either --proposal or --kontext-proposal, not both")
    missing = [str(path) for path in (args.plate, args.cg, args.alpha) if not path.exists()]
    if args.proposal and not args.proposal.exists():
        missing.append(str(args.proposal))
    if missing:
        raise FileNotFoundError("missing inputs: " + ", ".join(missing))

    config = load_config(args.config)
    updates = {"backend": "latent_delta_proxy"}
    if args.kontext_proposal:
        args.proposal = _run_kontext_proposal(args)
    if args.proposal:
        updates["latent_proposal_path"] = str(args.proposal)
    if args.delta_blur is not None:
        updates["latent_delta_blur_px"] = args.delta_blur
    if args.luma_strength is not None:
        updates["latent_luma_strength"] = args.luma_strength
    if args.color_strength is not None:
        updates["latent_color_strength"] = args.color_strength
    config = replace(config, **updates)

    job_path = run_pipeline(
        PipelineInputs(plate_rgb=args.plate, cg_rgba=args.cg, alpha=args.alpha),
        args.output_dir,
        config,
    )
    print(f"wrote {job_path}")


if __name__ == "__main__":
    main()
