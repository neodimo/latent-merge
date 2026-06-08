#!/usr/bin/env python3
"""Run a short sequence through the pipeline and score frame-to-frame flicker."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEQUENCE_DIR = ROOT / "fixtures" / "synthetic_sequence_001"
DEFAULT_OUTPUT_DIR = ROOT / "runs" / "phase2_sequence_synthetic_001"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTORCH_JIT", "0")

from core.pipeline import PipelineInputs, load_config, run_pipeline


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def _load_alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)[..., None] / 255.0


def _frame_dirs(sequence_dir: Path) -> list[Path]:
    manifest = sequence_dir / "sequence.json"
    if manifest.is_file():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        return [sequence_dir / frame["directory"] for frame in payload.get("frames", [])]
    return sorted(path for path in sequence_dir.glob("frame_*") if path.is_dir())


def _peak_vram_mb(frame_records: list[dict[str, Any]]) -> float | None:
    peaks: list[float] = []
    for record in frame_records:
        gpu = record.get("runtime", {}).get("gpu_memory", {})
        value = gpu.get("max_reserved_mb") or gpu.get("max_allocated_mb")
        if isinstance(value, (int, float)):
            peaks.append(float(value))
    return round(max(peaks), 2) if peaks else None


def _score_pair(prev_dir: Path, curr_dir: Path) -> dict[str, float]:
    prev_comp = _load_rgb(prev_dir / "final_comp.png")
    curr_comp = _load_rgb(curr_dir / "final_comp.png")
    prev_alpha = _load_alpha(prev_dir / "alpha_used.png")
    curr_alpha = _load_alpha(curr_dir / "alpha_used.png")
    shared_alpha = np.minimum(prev_alpha, curr_alpha)
    mask = shared_alpha[..., 0] > 0.1
    if not bool(mask.any()):
        return {
            "final_comp_temporal_rmse": 0.0,
            "foreground_temporal_rmse": 0.0,
            "alpha_pixels": 0,
        }

    prev_fg = _load_rgb(prev_dir / "adjusted_fg.png")
    curr_fg = _load_rgb(curr_dir / "adjusted_fg.png")
    comp_rmse = float(np.sqrt(((curr_comp - prev_comp) ** 2)[mask].mean()))
    fg_rmse = float(np.sqrt(((curr_fg - prev_fg) ** 2)[mask].mean()))
    return {
        "final_comp_temporal_rmse": round(comp_rmse, 6),
        "foreground_temporal_rmse": round(fg_rmse, 6),
        "alpha_pixels": int(mask.sum()),
    }


def evaluate_sequence(sequence_dir: Path, output_dir: Path, config_path: Path | None) -> Path:
    frame_dirs = _frame_dirs(sequence_dir)
    if len(frame_dirs) < 2:
        raise ValueError(f"{sequence_dir} must contain at least two frame directories")

    config = load_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_records: list[dict[str, Any]] = []

    for index, frame_dir in enumerate(frame_dirs):
        missing = [
            str(path)
            for path in (frame_dir / "plate_rgb.png", frame_dir / "cg_rgba.png", frame_dir / "alpha.png")
            if not path.is_file()
        ]
        if missing:
            raise FileNotFoundError("missing sequence frame inputs: " + ", ".join(missing))

        frame_out = output_dir / f"frame_{index:03d}"
        job_path = run_pipeline(
            PipelineInputs(
                plate_rgb=frame_dir / "plate_rgb.png",
                cg_rgba=frame_dir / "cg_rgba.png",
                alpha=frame_dir / "alpha.png",
            ),
            frame_out,
            config,
        )
        job = json.loads(job_path.read_text(encoding="utf-8"))
        frame_records.append(
            {
                "frame": index,
                "source": str(frame_dir),
                "job": str(job_path),
                "outputs": job.get("outputs", {}),
                "runtime": job.get("runtime", {}),
            }
        )

    pair_metrics = []
    for index in range(1, len(frame_records)):
        prev_dir = Path(frame_records[index - 1]["job"]).parent
        curr_dir = Path(frame_records[index]["job"]).parent
        pair_metrics.append({"from": index - 1, "to": index, **_score_pair(prev_dir, curr_dir)})

    comp_values = [pair["final_comp_temporal_rmse"] for pair in pair_metrics]
    fg_values = [pair["foreground_temporal_rmse"] for pair in pair_metrics]
    durations = [
        record.get("runtime", {}).get("duration_s")
        for record in frame_records
        if isinstance(record.get("runtime", {}).get("duration_s"), (int, float))
    ]
    report = {
        "schema": "latent-merge.sequence-flicker.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "sequence": str(sequence_dir),
        "config": str(config_path) if config_path else None,
        "backend": config.backend,
        "frame_count": len(frame_records),
        "frames": frame_records,
        "pair_metrics": pair_metrics,
        "summary": {
            "max_final_comp_temporal_rmse": round(max(comp_values), 6) if comp_values else 0.0,
            "mean_final_comp_temporal_rmse": round(float(np.mean(comp_values)), 6) if comp_values else 0.0,
            "max_foreground_temporal_rmse": round(max(fg_values), 6) if fg_values else 0.0,
            "mean_foreground_temporal_rmse": round(float(np.mean(fg_values)), 6) if fg_values else 0.0,
            "mean_frame_runtime_s": round(float(np.mean(durations)), 4) if durations else None,
            "max_frame_runtime_s": round(max(durations), 4) if durations else None,
            "peak_vram_reserved_mb": _peak_vram_mb(frame_records),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        },
    }
    report_path = output_dir / "sequence_metrics.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate sequence flicker with the Phase 1 pipeline.")
    parser.add_argument("--sequence-dir", type=Path, default=DEFAULT_SEQUENCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    report = evaluate_sequence(args.sequence_dir, args.output_dir, args.config)
    print(f"wrote {report}")


if __name__ == "__main__":
    main()
