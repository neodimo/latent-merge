from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from core.image_io import load_alpha, load_rgb, load_rgba, save_alpha, save_rgb, save_rgba, sha256_file


@dataclass(frozen=True)
class PipelineInputs:
    plate_rgb: Path
    cg_rgba: Path
    alpha: Path


@dataclass(frozen=True)
class PipelineConfig:
    backend: str = "mean_match_stub"
    tier: str = "mid-16"          # compact-8 | mid-16 | full-48
    notes: str = "Phase 1 scaffold backend; replace with real model runner."
    adjustment_strength: float = 1.0
    delta_preview_gain: float = 1.0
    correction_softness_px: float = 0.0
    correction_choke_px: int = 0

    def validate(self) -> None:
        allowed_backends = {"mean_match_stub", "pctnet"}
        if self.backend not in allowed_backends:
            raise ValueError(f"unsupported backend '{self.backend}'; available: {', '.join(sorted(allowed_backends))}")
        allowed_tiers = {"compact-8", "mid-16", "full-48"}
        if self.tier not in allowed_tiers:
            raise ValueError(f"unsupported tier '{self.tier}'; available: {', '.join(sorted(allowed_tiers))}")
        if not 0.0 <= self.adjustment_strength <= 2.5:
            raise ValueError("adjustment_strength must be between 0.0 and 2.5")
        if not 1.0 <= self.delta_preview_gain <= 16.0:
            raise ValueError("delta_preview_gain must be between 1.0 and 16.0")
        if not 0.0 <= self.correction_softness_px <= 24.0:
            raise ValueError("correction_softness_px must be between 0.0 and 24.0")
        if not -24 <= self.correction_choke_px <= 24:
            raise ValueError("correction_choke_px must be between -24 and 24")


def load_config(path: Path | None) -> PipelineConfig:
    if path is None:
        return PipelineConfig()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PipelineConfig(
        backend=payload.get("backend", PipelineConfig.backend),
        tier=payload.get("tier", PipelineConfig.tier),
        notes=payload.get("notes", PipelineConfig.notes),
        adjustment_strength=payload.get("adjustment_strength", PipelineConfig.adjustment_strength),
        delta_preview_gain=payload.get("delta_preview_gain", PipelineConfig.delta_preview_gain),
        correction_softness_px=payload.get("correction_softness_px", PipelineConfig.correction_softness_px),
        correction_choke_px=payload.get("correction_choke_px", PipelineConfig.correction_choke_px),
    )


def _load_pctnet(tier: str):
    from models.pctnet.pctnet_harmonizer import PCTNetHarmonizer
    import pathlib
    weight_path = pathlib.Path(__file__).parent.parent / "models" / "pctnet" / "PCTNet_CNN.pth"
    return PCTNetHarmonizer(weight_path=str(weight_path), device=None, tier=tier)


def _harmonize_pctnet(
    model_rgb: np.ndarray,
    alpha: np.ndarray,
    harmonizer,
) -> np.ndarray:
    """Run PCT-Net with composite context, returning an adjusted foreground.

    PCT-Net needs background context to estimate the foreground color transform.
    The model can see the composited plate, but the pipeline still preserves the
    contract by only saving/re-compositing foreground pixels over the original
    plate.
    """
    return harmonizer.harmonize(model_rgb, alpha)


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


def _correction_matte(alpha: np.ndarray, choke_px: int, softness_px: float) -> np.ndarray:
    matte = np.clip(alpha[..., 0] if alpha.ndim == 3 else alpha, 0.0, 1.0)
    image = Image.fromarray((matte * 255.0).astype(np.uint8), mode="L")
    if choke_px:
        filter_size = abs(choke_px) * 2 + 1
        image = image.filter(ImageFilter.MinFilter(filter_size) if choke_px > 0 else ImageFilter.MaxFilter(filter_size))
    if softness_px:
        image = image.filter(ImageFilter.GaussianBlur(float(softness_px)))
    return (np.asarray(image, dtype=np.float32) / 255.0)[..., None]


def run_pipeline(inputs: PipelineInputs, output_dir: Path, config: PipelineConfig) -> Path:
    config.validate()
    output_dir.mkdir(parents=True, exist_ok=True)
    plate = load_rgb(inputs.plate_rgb)
    cg_rgb, cg_alpha = load_rgba(inputs.cg_rgba)
    external_alpha = load_alpha(inputs.alpha)

    if plate.shape != cg_rgb.shape or external_alpha.shape[:2] != plate.shape[:2]:
        raise ValueError(
            f"dimension mismatch: plate={plate.shape}, cg={cg_rgb.shape}, alpha={external_alpha.shape}"
        )

    combined_alpha = np.minimum(external_alpha, cg_alpha)
    correction_matte = _correction_matte(
        combined_alpha,
        choke_px=config.correction_choke_px,
        softness_px=config.correction_softness_px,
    )

    if config.backend == "mean_match_stub":
        model_adjusted_rgb, backend_report = _mean_match_stub(plate, cg_rgb, combined_alpha)
    elif config.backend == "pctnet":
        model = _load_pctnet(tier=config.tier)
        model_input = cg_rgb * combined_alpha + plate * (1.0 - combined_alpha)
        harmonized_composite = _harmonize_pctnet(model_input, combined_alpha, model)
        alpha_safe = np.maximum(combined_alpha, 1e-6)
        model_adjusted_rgb = (harmonized_composite - plate * (1.0 - combined_alpha)) / alpha_safe
        model_adjusted_rgb = np.where(combined_alpha > 1e-6, model_adjusted_rgb, cg_rgb)
        model_adjusted_rgb = np.clip(model_adjusted_rgb, 0.0, 1.0)
        backend_report = {
            "name": "pctnet",
            "model_type": "PCTNet",
            "model_variant": "CNN",
            "tier": config.tier,
            "model_input": "composite_rgb_plus_alpha_mask",
            "foreground_reconstruction": "harmonized_composite_minus_plate_divided_by_alpha",
        }
    else:
        raise ValueError(f"unsupported backend '{config.backend}'")

    adjusted_rgb = cg_rgb + (model_adjusted_rgb - cg_rgb) * config.adjustment_strength * correction_matte
    adjusted_rgb = np.clip(adjusted_rgb, 0.0, 1.0)
    raw_a_over_b = cg_rgb * combined_alpha + plate * (1.0 - combined_alpha)
    final_comp = adjusted_rgb * combined_alpha + plate * (1.0 - combined_alpha)
    delta = np.abs(adjusted_rgb - cg_rgb)
    alpha_weighted_delta = delta * combined_alpha
    delta_visual = np.clip(delta * config.delta_preview_gain, 0.0, 1.0)
    alpha_weighted_delta_visual = np.clip(alpha_weighted_delta * config.delta_preview_gain, 0.0, 1.0)

    outputs = {
        "raw_a_over_b": output_dir / "raw_a_over_b.png",
        "adjusted_fg": output_dir / "adjusted_fg.png",
        "final_comp": output_dir / "final_comp.png",
        "delta": output_dir / "delta.png",
        "alpha_weighted_delta": output_dir / "alpha_weighted_delta.png",
        "alpha_used": output_dir / "alpha_used.png",
        "correction_matte": output_dir / "correction_matte.png",
        "job": output_dir / "job.json",
    }

    save_rgb(outputs["raw_a_over_b"], raw_a_over_b)
    save_rgba(outputs["adjusted_fg"], adjusted_rgb, combined_alpha)
    save_rgb(outputs["final_comp"], final_comp)
    save_rgb(outputs["delta"], delta_visual)
    save_rgb(outputs["alpha_weighted_delta"], alpha_weighted_delta_visual)
    save_alpha(outputs["alpha_used"], combined_alpha)
    save_alpha(outputs["correction_matte"], correction_matte)

    job = {
        "schema": "latent-merge.phase1-run.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "backend": config.backend,
            "tier": config.tier,
            "notes": config.notes,
            "adjustment_strength": config.adjustment_strength,
            "delta_preview_gain": config.delta_preview_gain,
            "correction_softness_px": config.correction_softness_px,
            "correction_choke_px": config.correction_choke_px,
        },
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
            "interaction_passes": ["delta", "alpha_weighted_delta", "correction_matte"],
        },
    }
    outputs["job"].write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return outputs["job"]
