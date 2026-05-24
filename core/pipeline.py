from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from core.image_io import load_alpha, load_rgb, load_rgba, save_alpha, save_rgb, save_rgba, sha256_file


@dataclass(frozen=True)
class PipelineInputs:
    plate_rgb: Path
    cg_rgba: Path
    alpha: Path


@dataclass(frozen=True)
class PipelineConfig:
    backend: str = "mean_match_stub"
    notes: str = "Phase 1 scaffold backend; replace with real model runner."


def load_config(path: Path | None) -> PipelineConfig:
    if path is None:
        return PipelineConfig()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PipelineConfig(
        backend=payload.get("backend", PipelineConfig.backend),
        notes=payload.get("notes", PipelineConfig.notes),
    )


def _mean_match_stub(plate: np.ndarray, cg_rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    alpha_weight = np.maximum(alpha, 1e-6)
    plate_mean = (plate * alpha).sum(axis=(0, 1)) / alpha_weight.sum()
    cg_mean = (cg_rgb * alpha).sum(axis=(0, 1)) / alpha_weight.sum()
    gain = np.clip(plate_mean / np.maximum(cg_mean, 1e-4), 0.72, 1.28)
    adjusted_rgb = np.clip(cg_rgb * gain[None, None, :], 0.0, 1.0)
    return adjusted_rgb, {
        "name": "mean_match_stub",
        "plate_mean_under_alpha": plate_mean.round(6).tolist(),
        "cg_mean_under_alpha": cg_mean.round(6).tolist(),
        "rgb_gain": gain.round(6).tolist(),
    }


def run_pipeline(inputs: PipelineInputs, output_dir: Path, config: PipelineConfig) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    plate = load_rgb(inputs.plate_rgb)
    cg_rgb, cg_alpha = load_rgba(inputs.cg_rgba)
    external_alpha = load_alpha(inputs.alpha)

    if plate.shape != cg_rgb.shape or external_alpha.shape[:2] != plate.shape[:2]:
        raise ValueError(
            f"dimension mismatch: plate={plate.shape}, cg={cg_rgb.shape}, alpha={external_alpha.shape}"
        )

    combined_alpha = np.minimum(external_alpha, cg_alpha)

    if config.backend != "mean_match_stub":
        raise ValueError(f"unsupported backend '{config.backend}'; available: mean_match_stub")

    adjusted_rgb, backend_report = _mean_match_stub(plate, cg_rgb, combined_alpha)
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
    save_alpha(outputs["alpha_used"], combined_alpha)

    job = {
        "schema": "latent-merge.phase1-run.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": {"backend": config.backend, "notes": config.notes},
        "inputs": {
            "plate_rgb": {"path": str(inputs.plate_rgb), "sha256": sha256_file(inputs.plate_rgb)},
            "cg_rgba": {"path": str(inputs.cg_rgba), "sha256": sha256_file(inputs.cg_rgba)},
            "alpha": {"path": str(inputs.alpha), "sha256": sha256_file(inputs.alpha)},
        },
        "outputs": {key: str(path) for key, path in outputs.items() if key != "job"},
        "backend_report": backend_report,
        "contract": {
            "plate_repainted": False,
            "primary_model_output": "adjusted foreground RGBA",
            "trusted_composite": "normal A-over-B over original plate",
            "interaction_passes": [],
        },
    }
    outputs["job"].write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return outputs["job"]
