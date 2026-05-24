#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from core.pipeline import PipelineInputs, load_config, run_pipeline


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = ROOT / "fixtures" / "golden_synthetic_001"
DEFAULT_OUTPUT_DIR = ROOT / "runs" / "phase1_scaffold"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 1 latent-merge pipeline scaffold.")
    parser.add_argument("--plate", type=Path, default=DEFAULT_FIXTURE_DIR / "plate_rgb.png")
    parser.add_argument("--cg", type=Path, default=DEFAULT_FIXTURE_DIR / "cg_rgba.png")
    parser.add_argument("--alpha", type=Path, default=DEFAULT_FIXTURE_DIR / "alpha.png")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    missing = [str(path) for path in (args.plate, args.cg, args.alpha) if not path.exists()]
    if missing:
        raise FileNotFoundError("missing inputs: " + ", ".join(missing))

    job_path = run_pipeline(
        PipelineInputs(plate_rgb=args.plate, cg_rgba=args.cg, alpha=args.alpha),
        args.output_dir,
        load_config(args.config),
    )
    print(f"wrote {job_path}")


if __name__ == "__main__":
    main()
