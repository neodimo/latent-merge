from __future__ import annotations

import json
import os
import subprocess
import sys
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
    vit_context: float = 0.45
    vit_contrast: float = 0.65
    vit_warmth: float = 0.0
    vit_saturation: float = 1.0
    vit_identity_lock: float = 0.35
    ic_flux_seed: int = 42
    ic_flux_steps: int = 20
    ic_flux_cfg: float = 3.5
    ic_flux_cond_strength: float = 0.75
    ic_flux_resolution: int = 768
    ic_flux_fp16: bool = True

    def validate(self) -> None:
        allowed_backends = {"mean_match_stub", "pctnet", "pctnet_vit_proxy", "ic_flux_v2"}
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
        if not 0.0 <= self.vit_context <= 1.0:
            raise ValueError("vit_context must be between 0.0 and 1.0")
        if not 0.0 <= self.vit_contrast <= 1.5:
            raise ValueError("vit_contrast must be between 0.0 and 1.5")
        if not -1.0 <= self.vit_warmth <= 1.0:
            raise ValueError("vit_warmth must be between -1.0 and 1.0")
        if not 0.0 <= self.vit_saturation <= 2.0:
            raise ValueError("vit_saturation must be between 0.0 and 2.0")
        if not 0.0 <= self.vit_identity_lock <= 1.0:
            raise ValueError("vit_identity_lock must be between 0.0 and 1.0")
        if not 1 <= self.ic_flux_steps <= 60:
            raise ValueError("ic_flux_steps must be between 1 and 60")
        if not 1.0 <= self.ic_flux_cfg <= 10.0:
            raise ValueError("ic_flux_cfg must be between 1.0 and 10.0")
        if not 0.0 <= self.ic_flux_cond_strength <= 1.5:
            raise ValueError("ic_flux_cond_strength must be between 0.0 and 1.5")
        if not 384 <= self.ic_flux_resolution <= 1536:
            raise ValueError("ic_flux_resolution must be between 384 and 1536")


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
        vit_context=payload.get("vit_context", PipelineConfig.vit_context),
        vit_contrast=payload.get("vit_contrast", PipelineConfig.vit_contrast),
        vit_warmth=payload.get("vit_warmth", PipelineConfig.vit_warmth),
        vit_saturation=payload.get("vit_saturation", PipelineConfig.vit_saturation),
        vit_identity_lock=payload.get("vit_identity_lock", PipelineConfig.vit_identity_lock),
        ic_flux_seed=payload.get("ic_flux_seed", PipelineConfig.ic_flux_seed),
        ic_flux_steps=payload.get("ic_flux_steps", PipelineConfig.ic_flux_steps),
        ic_flux_cfg=payload.get("ic_flux_cfg", PipelineConfig.ic_flux_cfg),
        ic_flux_cond_strength=payload.get("ic_flux_cond_strength", PipelineConfig.ic_flux_cond_strength),
        ic_flux_resolution=payload.get("ic_flux_resolution", PipelineConfig.ic_flux_resolution),
        ic_flux_fp16=payload.get("ic_flux_fp16", PipelineConfig.ic_flux_fp16),
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
    config: PipelineConfig,
) -> tuple[np.ndarray, dict[str, Any]]:
    global_adjusted, global_report = _match_mean_std(plate, cg_rgb, alpha, config.vit_contrast)
    radius = max(1, int(round(2 + config.vit_context * 7)))
    local_alpha = _blur_alpha(alpha, radius)
    local_adjusted, local_report = _match_mean_std(plate, cg_rgb, local_alpha, config.vit_contrast * 0.8)
    target = global_adjusted * (1.0 - config.vit_context) + local_adjusted * config.vit_context

    warm_bias = np.array([0.035, 0.006, -0.03], dtype=np.float32) * config.vit_warmth
    target = np.clip(target + warm_bias[None, None, :], 0.0, 1.0)

    luminance = (target * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=2, keepdims=True)
    target = np.clip(luminance + (target - luminance) * config.vit_saturation, 0.0, 1.0)
    adjusted = cg_rgb * config.vit_identity_lock + target * (1.0 - config.vit_identity_lock)
    return np.clip(adjusted, 0.0, 1.0), {
        "name": "pctnet_vit_proxy",
        "model_type": "PCTNet",
        "model_variant": "ViT proxy",
        "status": "local controllable proxy; ViT checkpoint is not bundled in this release",
        "vit_context": config.vit_context,
        "vit_contrast": config.vit_contrast,
        "vit_warmth": config.vit_warmth,
        "vit_saturation": config.vit_saturation,
        "vit_identity_lock": config.vit_identity_lock,
        "local_alpha_radius_px": radius,
        "global_statistics": global_report,
        "local_statistics": local_report,
    }


def _load_ic_flux_output(output_dir: Path) -> np.ndarray:
    from PIL import Image

    path = output_dir / "adjusted_fg.png"
    if not path.is_file():
        raise RuntimeError("IC Flux runner completed without adjusted_fg.png")
    image = Image.open(path).convert("RGB")
    return np.asarray(image, dtype=np.float32) / 255.0


def _run_ic_flux_v2(inputs: PipelineInputs, output_dir: Path, config: PipelineConfig) -> tuple[np.ndarray, dict[str, Any]]:
    if os.environ.get("LATENT_MERGE_ENABLE_IC_FLUX") != "1":
        raise RuntimeError(
            "IC Flux v2 is an external GPU backend. Set LATENT_MERGE_ENABLE_IC_FLUX=1 after installing "
            "CUDA torch, diffusers, transformers, accelerate, and local weights under weights/ic-light-v2 "
            "and weights/flux1-dev. See scripts/run_ic_flux_comparison.sh."
        )

    runner = Path(__file__).resolve().parents[1] / "scripts" / "ic_flux_runner.py"
    weights_dir = Path(os.environ.get("LATENT_MERGE_IC_FLUX_WEIGHTS", "weights/ic-light-v2"))
    flux_weights_dir = Path(os.environ.get("LATENT_MERGE_FLUX_WEIGHTS", "weights/flux1-dev"))
    ic_dir = output_dir / "ic_flux_v2_external"
    command = [
        sys.executable,
        str(runner),
        "--plate",
        str(inputs.plate_rgb),
        "--cg",
        str(inputs.cg_rgba),
        "--alpha",
        str(inputs.alpha),
        "--seed",
        str(config.ic_flux_seed),
        "--steps",
        str(config.ic_flux_steps),
        "--cfg",
        str(config.ic_flux_cfg),
        "--cond-strength",
        str(config.ic_flux_cond_strength),
        "--resolution",
        str(config.ic_flux_resolution),
        "--weights-dir",
        str(weights_dir),
        "--flux-weights-dir",
        str(flux_weights_dir),
        "--out-dir",
        str(ic_dir),
    ]
    if not config.ic_flux_fp16:
        command.append("--no-fp16")

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60 * 30)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(f"IC Flux v2 failed: {detail}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("IC Flux v2 timed out after 30 minutes") from error

    adjusted = _load_ic_flux_output(ic_dir)
    job_path = ic_dir / "job.json"
    external_job = json.loads(job_path.read_text(encoding="utf-8")) if job_path.is_file() else {}
    return adjusted, {
        "name": "ic_flux_v2",
        "model_type": "IC-Light V2 / FLUX",
        "model_variant": "external GPU runner",
        "seed": config.ic_flux_seed,
        "steps": config.ic_flux_steps,
        "cfg": config.ic_flux_cfg,
        "cond_strength": config.ic_flux_cond_strength,
        "resolution": config.ic_flux_resolution,
        "fp16": config.ic_flux_fp16,
        "weights_dir": str(weights_dir),
        "flux_weights_dir": str(flux_weights_dir),
        "runner_stdout_tail": result.stdout[-2000:],
        "external_job": external_job,
    }


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
    elif config.backend == "pctnet_vit_proxy":
        model_adjusted_rgb, backend_report = _pctnet_vit_proxy(plate, cg_rgb, combined_alpha, config)
    elif config.backend == "ic_flux_v2":
        model_adjusted_rgb, backend_report = _run_ic_flux_v2(inputs, output_dir, config)
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
            "vit_context": config.vit_context,
            "vit_contrast": config.vit_contrast,
            "vit_warmth": config.vit_warmth,
            "vit_saturation": config.vit_saturation,
            "vit_identity_lock": config.vit_identity_lock,
            "ic_flux_seed": config.ic_flux_seed,
            "ic_flux_steps": config.ic_flux_steps,
            "ic_flux_cfg": config.ic_flux_cfg,
            "ic_flux_cond_strength": config.ic_flux_cond_strength,
            "ic_flux_resolution": config.ic_flux_resolution,
            "ic_flux_fp16": config.ic_flux_fp16,
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
