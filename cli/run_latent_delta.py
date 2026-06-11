#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    missing = [str(path) for path in (args.plate, args.cg, args.alpha) if not path.exists()]
    if args.proposal and not args.proposal.exists():
        missing.append(str(args.proposal))
    if missing:
        raise FileNotFoundError("missing inputs: " + ", ".join(missing))

    config = load_config(args.config)
    updates = {"backend": "latent_delta_proxy"}
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
