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
    parameters: dict[str, float] | None = None


def load_config(path: Path | None, overrides: dict[str, Any] | None = None) -> PipelineConfig:
    overrides = overrides or {}
    if path is None:
        payload: dict[str, Any] = {}
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))

    parameters = dict(payload.get("parameters", {}))
    parameters.update(overrides.get("parameters", {}))

    backend = overrides.get("backend", payload.get("backend", PipelineConfig.backend))
    notes = overrides.get("notes", payload.get("notes", PipelineConfig.notes))
    return PipelineConfig(
        backend=backend,
        notes=notes,
        parameters={key: float(value) for key, value in parameters.items()},
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


def _clamp_param(parameters: dict[str, float], key: str, default: float, lo: float, hi: float) -> float:
    return float(np.clip(parameters.get(key, default), lo, hi))


def _blur_alpha(alpha: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return alpha
    padded = np.pad(alpha, ((radius, radius), (radius, radius), (0, 0)), mode="edge")
    result = np.zeros_like(alpha)
    samples = 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            result += padded[
                radius + dy : radius + dy + alpha.shape[0],
                radius + dx : radius + dx + alpha.shape[1],
                :,
            ]
            samples += 1
    return result / max(samples, 1)


def _match_mean_std(
    plate: np.ndarray,
    cg_rgb: np.ndarray,
    alpha: np.ndarray,
    contrast: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    alpha_weight = np.maximum(alpha, 1e-6)
    total = alpha_weight.sum()
    plate_mean = (plate * alpha).sum(axis=(0, 1)) / total
    cg_mean = (cg_rgb * alpha).sum(axis=(0, 1)) / total
    plate_std = np.sqrt(((plate - plate_mean[None, None, :]) ** 2 * alpha).sum(axis=(0, 1)) / total + 1e-8)
    cg_std = np.sqrt(((cg_rgb - cg_mean[None, None, :]) ** 2 * alpha).sum(axis=(0, 1)) / total + 1e-8)
    scale = np.clip(plate_std / np.maximum(cg_std, 1e-6), 0.35, 2.8)
    scale = 1.0 + (scale - 1.0) * contrast
    adjusted = (cg_rgb - cg_mean[None, None, :]) * scale[None, None, :] + plate_mean[None, None, :]
    return np.clip(adjusted, 0.0, 1.0), {
        "plate_mean": plate_mean.round(6).tolist(),
        "cg_mean": cg_mean.round(6).tolist(),
        "plate_std": plate_std.round(6).tolist(),
        "cg_std": cg_std.round(6).tolist(),
        "contrast_scale": scale.round(6).tolist(),
    }


def _pctnet_vit_proxy(
    plate: np.ndarray,
    cg_rgb: np.ndarray,
    alpha: np.ndarray,
    parameters: dict[str, float],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Local controllable proxy for the stronger PCT-Net ViT lane.

    This keeps the Phase 1 contract intact while the external checkpoint runner
    is stabilized. It uses global + coarse local color statistics to mimic the
    broader context response Omid asked to expose in the UI.
    """
    strength = _clamp_param(parameters, "strength", 1.0, 0.0, 2.0)
    locality = _clamp_param(parameters, "locality", 0.45, 0.0, 1.0)
    contrast = _clamp_param(parameters, "contrast", 0.65, 0.0, 1.5)
    warmth = _clamp_param(parameters, "warmth", 0.0, -1.0, 1.0)
    saturation = _clamp_param(parameters, "saturation", 1.0, 0.0, 2.0)
    identity_lock = _clamp_param(parameters, "identity_lock", 0.35, 0.0, 1.0)

    global_adjusted, global_report = _match_mean_std(plate, cg_rgb, alpha, contrast)
    radius = max(1, int(round(2 + locality * 7)))
    local_alpha = _blur_alpha(alpha, radius)
    local_adjusted, local_report = _match_mean_std(plate, cg_rgb, local_alpha, contrast * 0.8)

    target = global_adjusted * (1.0 - locality) + local_adjusted * locality
    target = np.clip(cg_rgb + (target - cg_rgb) * strength, 0.0, 1.0)

    warm_bias = np.array([0.035, 0.006, -0.03], dtype=np.float32) * warmth
    target = np.clip(target + warm_bias[None, None, :], 0.0, 1.0)

    luminance = (target * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=2, keepdims=True)
    target = np.clip(luminance + (target - luminance) * saturation, 0.0, 1.0)

    adjusted = cg_rgb * identity_lock + target * (1.0 - identity_lock)
    return np.clip(adjusted, 0.0, 1.0), {
        "name": "pctnet_vit_proxy",
        "status": "local controllable proxy; external PCT-Net ViT checkpoint not bundled",
        "parameters": {
            "strength": strength,
            "locality": locality,
            "contrast": contrast,
            "warmth": warmth,
            "saturation": saturation,
            "identity_lock": identity_lock,
        },
        "global_statistics": global_report,
        "local_statistics": local_report,
        "local_alpha_radius_px": radius,
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

    parameters = config.parameters or {}
    if config.backend == "mean_match_stub":
        adjusted_rgb, backend_report = _mean_match_stub(plate, cg_rgb, combined_alpha)
    elif config.backend == "pctnet_vit_proxy":
        adjusted_rgb, backend_report = _pctnet_vit_proxy(plate, cg_rgb, combined_alpha, parameters)
    else:
        raise ValueError(f"unsupported backend '{config.backend}'; available: mean_match_stub, pctnet_vit_proxy")

    final_comp = adjusted_rgb * combined_alpha + plate * (1.0 - combined_alpha)
    delta = np.abs(adjusted_rgb - cg_rgb)
    alpha_weighted_delta = delta * combined_alpha
    delta_display_gain = _clamp_param(parameters, "delta_display_gain", 1.0, 1.0, 8.0)
    delta_view = np.clip(delta * delta_display_gain, 0.0, 1.0)
    alpha_weighted_delta_view = np.clip(alpha_weighted_delta * delta_display_gain, 0.0, 1.0)

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
    save_rgb(outputs["delta"], delta_view)
    save_rgb(outputs["alpha_weighted_delta"], alpha_weighted_delta_view)
    save_alpha(outputs["alpha_used"], combined_alpha)

    job = {
        "schema": "latent-merge.phase1-run.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "backend": config.backend,
            "notes": config.notes,
            "parameters": parameters,
            "delta_display_gain": delta_display_gain,
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
            "interaction_passes": [],
        },
    }
    outputs["job"].write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return outputs["job"]
