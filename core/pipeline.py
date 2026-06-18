from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from core.image_io import load_alpha, load_rgb, load_rgba, save_alpha, save_rgb, save_rgba, sha256_file

try:
    import resource
except ImportError:  # pragma: no cover - Windows packaged UI path.
    resource = None


IC_FLUX_REQUIRED_MODULES = {
    "numpy": "numpy",
    "PIL": "Pillow",
    "torch": "torch",
    "diffusers": "diffusers",
    "transformers": "transformers",
    "accelerate": "accelerate",
    "huggingface_hub": "huggingface_hub",
    "safetensors": "safetensors",
}


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
    latent_proposal_path: str = ""
    latent_delta_blur_px: float = 18.0
    latent_luma_strength: float = 1.0
    latent_color_strength: float = 0.35
    latent_shadow_strength: float = 0.0
    latent_shadow_offset_x: int = 14
    latent_shadow_offset_y: int = 18
    latent_shadow_blur_px: float = 18.0
    latent_shadow_expand_px: int = 12

    def validate(self) -> None:
        allowed_backends = {"mean_match_stub", "pctnet", "pctnet_vit_proxy", "ic_flux_v2", "latent_delta_proxy"}
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
        if not 1.0 <= self.latent_delta_blur_px <= 96.0:
            raise ValueError("latent_delta_blur_px must be between 1.0 and 96.0")
        if not 0.0 <= self.latent_luma_strength <= 2.0:
            raise ValueError("latent_luma_strength must be between 0.0 and 2.0")
        if not 0.0 <= self.latent_color_strength <= 1.0:
            raise ValueError("latent_color_strength must be between 0.0 and 1.0")
        if not 0.0 <= self.latent_shadow_strength <= 0.85:
            raise ValueError("latent_shadow_strength must be between 0.0 and 0.85")
        if not -256 <= self.latent_shadow_offset_x <= 256:
            raise ValueError("latent_shadow_offset_x must be between -256 and 256")
        if not -256 <= self.latent_shadow_offset_y <= 256:
            raise ValueError("latent_shadow_offset_y must be between -256 and 256")
        if not 0.0 <= self.latent_shadow_blur_px <= 96.0:
            raise ValueError("latent_shadow_blur_px must be between 0.0 and 96.0")
        if not 0 <= self.latent_shadow_expand_px <= 96:
            raise ValueError("latent_shadow_expand_px must be between 0 and 96")


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
        latent_proposal_path=payload.get("latent_proposal_path", PipelineConfig.latent_proposal_path),
        latent_delta_blur_px=payload.get("latent_delta_blur_px", PipelineConfig.latent_delta_blur_px),
        latent_luma_strength=payload.get("latent_luma_strength", PipelineConfig.latent_luma_strength),
        latent_color_strength=payload.get("latent_color_strength", PipelineConfig.latent_color_strength),
        latent_shadow_strength=payload.get("latent_shadow_strength", PipelineConfig.latent_shadow_strength),
        latent_shadow_offset_x=payload.get("latent_shadow_offset_x", PipelineConfig.latent_shadow_offset_x),
        latent_shadow_offset_y=payload.get("latent_shadow_offset_y", PipelineConfig.latent_shadow_offset_y),
        latent_shadow_blur_px=payload.get("latent_shadow_blur_px", PipelineConfig.latent_shadow_blur_px),
        latent_shadow_expand_px=payload.get("latent_shadow_expand_px", PipelineConfig.latent_shadow_expand_px),
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


def _gaussian_blur_rgb(rgb: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0.0:
        return rgb
    image = Image.fromarray(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), mode="RGB")
    image = image.filter(ImageFilter.GaussianBlur(float(radius)))
    return np.asarray(image, dtype=np.float32) / 255.0


def _shadow_matte_from_alpha(alpha: np.ndarray, config: PipelineConfig) -> np.ndarray:
    matte = np.clip(alpha[..., 0], 0.0, 1.0)
    image = Image.fromarray((matte * 255.0).astype(np.uint8), mode="L")
    if config.latent_shadow_expand_px:
        image = image.filter(ImageFilter.MaxFilter(config.latent_shadow_expand_px * 2 + 1))
    if config.latent_shadow_blur_px:
        image = image.filter(ImageFilter.GaussianBlur(float(config.latent_shadow_blur_px)))
    expanded = np.asarray(image, dtype=np.float32) / 255.0

    shifted = np.zeros_like(expanded)
    dx = int(config.latent_shadow_offset_x)
    dy = int(config.latent_shadow_offset_y)
    src_y0 = max(0, -dy)
    src_y1 = expanded.shape[0] - max(0, dy)
    src_x0 = max(0, -dx)
    src_x1 = expanded.shape[1] - max(0, dx)
    dst_y0 = max(0, dy)
    dst_y1 = dst_y0 + max(0, src_y1 - src_y0)
    dst_x0 = max(0, dx)
    dst_x1 = dst_x0 + max(0, src_x1 - src_x0)
    if src_y1 > src_y0 and src_x1 > src_x0:
        shifted[dst_y0:dst_y1, dst_x0:dst_x1] = expanded[src_y0:src_y1, src_x0:src_x1]
    receiver = shifted * (1.0 - matte)
    return np.clip(receiver[..., None], 0.0, 1.0)


def _proposal_foreground_from_composite(
    proposal_rgb: np.ndarray,
    plate: np.ndarray,
    cg_rgb: np.ndarray,
    alpha: np.ndarray,
) -> np.ndarray:
    alpha_safe = np.maximum(alpha, 1e-4)
    recovered = (proposal_rgb - plate * (1.0 - alpha)) / alpha_safe
    return np.where(alpha > 1e-4, np.clip(recovered, 0.0, 1.0), cg_rgb)


def _load_latent_proposal(
    plate: np.ndarray,
    cg_rgb: np.ndarray,
    alpha: np.ndarray,
    config: PipelineConfig,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if config.latent_proposal_path:
        path = Path(config.latent_proposal_path).expanduser()
        proposal_rgb = load_rgb(path)
        if proposal_rgb.shape != plate.shape:
            raise ValueError(f"latent proposal shape mismatch: proposal={proposal_rgb.shape}, plate={plate.shape}")
        proposal_fg = _proposal_foreground_from_composite(proposal_rgb, plate, cg_rgb, alpha)
        return proposal_rgb, proposal_fg, {
            "source": "external_proposal",
            "path": str(path),
            "sha256": sha256_file(path) if path.is_file() else None,
            "interpretation": "RGB proposal composite; foreground recovered through alpha",
        }

    proposal_fg, proxy_report = _pctnet_vit_proxy(plate, cg_rgb, alpha, config)
    proposal_rgb = proposal_fg * alpha + plate * (1.0 - alpha)
    return proposal_rgb, proposal_fg, {
        "source": "local_proxy",
        "interpretation": "deterministic PCT/ViT-style proposal until FLUX edit/control proposal is wired",
        "proxy_report": proxy_report,
    }


def _latent_delta_proxy(
    plate: np.ndarray,
    cg_rgb: np.ndarray,
    alpha: np.ndarray,
    config: PipelineConfig,
) -> tuple[np.ndarray, dict[str, Any], dict[str, np.ndarray]]:
    proposal_rgb, proposal_fg, proposal_report = _load_latent_proposal(plate, cg_rgb, alpha, config)
    low_cg = _gaussian_blur_rgb(cg_rgb, config.latent_delta_blur_px)
    low_proposal = _gaussian_blur_rgb(proposal_fg, config.latent_delta_blur_px)
    luma_weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    cg_luma = np.maximum((low_cg * luma_weights).sum(axis=2, keepdims=True), 1e-4)
    proposal_luma = np.maximum((low_proposal * luma_weights).sum(axis=2, keepdims=True), 1e-4)
    luma_ratio = np.clip(proposal_luma / cg_luma, 0.45, 1.9)
    luma_scaled = cg_rgb * (1.0 + (luma_ratio - 1.0) * config.latent_luma_strength)
    color_delta = low_proposal - low_cg
    adjusted = luma_scaled + color_delta * config.latent_color_strength
    adjusted = np.clip(adjusted, 0.0, 1.0)

    shadow_matte = _shadow_matte_from_alpha(alpha, config)
    shadow_preview_comp = np.clip(plate * (1.0 - shadow_matte * config.latent_shadow_strength), 0.0, 1.0)
    lighting_delta = np.clip(np.abs(adjusted - cg_rgb) * alpha, 0.0, 1.0)
    model_proposal_fg_delta = np.clip(np.abs(proposal_fg - cg_rgb) * alpha, 0.0, 1.0)

    return adjusted, {
        "name": "latent_delta_proxy",
        "model_type": "Latent Merge constrained proposal/delta",
        "model_variant": "FLUX-edit-ready local proxy",
        "status": "runnable CLI/GUI scaffold; replace proposal source with FLUX Kontext/Fill/control output when available",
        "proposal": proposal_report,
        "delta_policy": {
            "locked_factors": ["shape", "silhouette", "identity", "material_detail", "plate_outside_interaction"],
            "changed_factors": ["low_frequency_foreground_lighting", "low_frequency_foreground_color"],
            "shadow_status": "staged_preview_only; not applied to final_comp until an interaction-mask gate exists",
        },
        "latent_delta_blur_px": config.latent_delta_blur_px,
        "latent_luma_strength": config.latent_luma_strength,
        "latent_color_strength": config.latent_color_strength,
        "latent_shadow_strength": config.latent_shadow_strength,
        "latent_shadow_offset": [config.latent_shadow_offset_x, config.latent_shadow_offset_y],
        "latent_shadow_blur_px": config.latent_shadow_blur_px,
        "latent_shadow_expand_px": config.latent_shadow_expand_px,
    }, {
        "model_proposal": proposal_rgb,
        "lighting_delta": lighting_delta,
        "model_proposal_fg_delta": model_proposal_fg_delta,
        "shadow_matte": shadow_matte,
        "shadow_preview_comp": shadow_preview_comp,
    }


def _load_ic_flux_output(output_dir: Path) -> np.ndarray:
    from PIL import Image

    path = output_dir / "adjusted_fg.png"
    if not path.is_file():
        raise RuntimeError("IC Flux runner completed without adjusted_fg.png")
    image = Image.open(path).convert("RGB")
    return np.asarray(image, dtype=np.float32) / 255.0


def _external_runner_env() -> dict[str, str]:
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        original_library_path = env.get("LD_LIBRARY_PATH_ORIG")
        if original_library_path is not None:
            env["LD_LIBRARY_PATH"] = original_library_path
        else:
            env.pop("LD_LIBRARY_PATH", None)
    return env


def _gpu_memory_snapshot() -> dict[str, Any]:
    try:
        import torch
    except Exception:
        return {"torch_available": False}

    snapshot: dict[str, Any] = {
        "torch_available": True,
        "cuda_available": bool(torch.cuda.is_available()),
    }
    if not torch.cuda.is_available():
        return snapshot

    device_index = torch.cuda.current_device()
    props = torch.cuda.get_device_properties(device_index)
    snapshot.update(
        {
            "device_index": device_index,
            "device_name": torch.cuda.get_device_name(device_index),
            "total_vram_mb": round(props.total_memory / (1024 * 1024)),
            "allocated_mb": round(torch.cuda.memory_allocated(device_index) / (1024 * 1024), 2),
            "reserved_mb": round(torch.cuda.memory_reserved(device_index) / (1024 * 1024), 2),
            "max_allocated_mb": round(torch.cuda.max_memory_allocated(device_index) / (1024 * 1024), 2),
            "max_reserved_mb": round(torch.cuda.max_memory_reserved(device_index) / (1024 * 1024), 2),
        }
    )
    return snapshot


def _reset_gpu_peak_memory() -> None:
    try:
        import torch
    except Exception:
        return
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def _process_max_rss_kb() -> int | None:
    if resource is None:
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _runtime_telemetry(start_time: float, start_rss_kb: int | None) -> dict[str, Any]:
    end_rss_kb = _process_max_rss_kb()
    rss_delta = None if start_rss_kb is None or end_rss_kb is None else round((end_rss_kb - start_rss_kb) / 1024, 2)
    return {
        "duration_s": round(time.perf_counter() - start_time, 4),
        "process_max_rss_mb": None if end_rss_kb is None else round(end_rss_kb / 1024, 2),
        "process_rss_delta_mb": rss_delta,
        "gpu_memory": _gpu_memory_snapshot(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }


def _fixture_metadata_for_input(path: Path) -> tuple[Path, dict[str, Any]] | None:
    """Return nearby fixture metadata for provenance stamping."""
    start = path.resolve().parent
    root = Path(__file__).resolve().parents[1]
    for directory in (start, *start.parents):
        for name in ("fixture.json", "manifest.json"):
            candidate = directory / name
            if candidate.is_file():
                return candidate, json.loads(candidate.read_text(encoding="utf-8"))
        if directory == root:
            break
    return None


def _input_provenance(inputs: PipelineInputs) -> dict[str, Any]:
    metadata = _fixture_metadata_for_input(inputs.plate_rgb)
    if metadata is None:
        return {
            "plate_provenance": "unknown",
            "source": f"no fixture metadata near {inputs.plate_rgb}",
        }
    metadata_path, payload = metadata
    value = payload.get("plate_provenance", "unknown")
    return {
        "plate_provenance": value if isinstance(value, str) else "unknown",
        "source": str(metadata_path),
    }


def _python_venv_candidates(root: Path) -> list[Path]:
    if os.name == "nt":
        return [root / ".ic-flux-venv" / "Scripts" / "python.exe", root / ".venv" / "Scripts" / "python.exe"]
    return [root / ".ic-flux-venv" / "bin" / "python", root / ".venv" / "bin" / "python"]


def _ic_flux_python_candidates() -> list[str]:
    candidates: list[str] = []
    managed_python = os.environ.get("LATENT_MERGE_IC_FLUX_PYTHON", "").strip()
    if managed_python:
        candidates.append(managed_python)
    env_python = os.environ.get("LATENT_MERGE_PYTHON", "").strip()
    if env_python:
        candidates.append(env_python)

    roots = [Path.cwd()]
    if not getattr(sys, "frozen", False):
        roots.append(Path(__file__).resolve().parents[1])
    for root in roots:
        candidates.extend(str(path) for path in _python_venv_candidates(root))

    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    candidates.extend(item for item in (shutil.which("python3"), shutil.which("python")) if item)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(Path(candidate).expanduser()) if os.sep in candidate or candidate.startswith("~") else candidate
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def resolve_ic_flux_python() -> str:
    candidates = _ic_flux_python_candidates()
    if not candidates:
        return "python3"
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return candidates[0]


def ic_flux_runtime_status(python_exe: str | None = None) -> dict[str, Any]:
    python_exe = python_exe or resolve_ic_flux_python()
    install_hint = (
        f"{python_exe} -m pip install numpy Pillow diffusers transformers accelerate huggingface_hub safetensors\n"
        f"{python_exe} -m pip install --force-reinstall torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121"
    )
    probe = """
import importlib.util
import json
import sys
required = {
    "numpy": "numpy",
    "PIL": "Pillow",
    "torch": "torch",
    "diffusers": "diffusers",
    "transformers": "transformers",
    "accelerate": "accelerate",
    "huggingface_hub": "huggingface_hub",
    "safetensors": "safetensors",
}
missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
payload = {"executable": sys.executable, "missing": missing, "versions": {}, "cuda_available": False, "gpu": None}
if not missing:
    import importlib.metadata
    for package in required.values():
        try:
            payload["versions"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            payload["versions"][package] = "unknown"
    import torch
    import torchvision
    if not hasattr(torch.ops, "torchvision") or not hasattr(torch.ops.torchvision, "nms"):
        payload["torchvision_error"] = "torchvision::nms operator is missing"
        print(json.dumps(payload))
        raise SystemExit(2)
    payload["torch_version"] = getattr(torch, "__version__", "unknown")
    payload["torchvision_version"] = getattr(torchvision, "__version__", "unknown")
    payload["cuda_available"] = bool(torch.cuda.is_available())
    if payload["cuda_available"]:
        props = torch.cuda.get_device_properties(0)
        payload["gpu"] = {
            "name": torch.cuda.get_device_name(0),
            "memory_mb": round(props.total_memory / (1024 * 1024)),
            "device_count": torch.cuda.device_count(),
        }
print(json.dumps(payload))
raise SystemExit(1 if missing else 0)
"""
    try:
        result = subprocess.run(
            [python_exe, "-c", probe],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=_external_runner_env(),
        )
    except FileNotFoundError:
        return {
            "ready": False,
            "python": python_exe,
            "missing": list(IC_FLUX_REQUIRED_MODULES.values()),
            "versions": {},
            "cuda_available": False,
            "gpu": None,
            "message": f"IC Flux Python was not found: {python_exe}",
            "install_hint": install_hint,
        }
    except subprocess.TimeoutExpired:
        return {
            "ready": False,
            "python": python_exe,
            "missing": [],
            "versions": {},
            "cuda_available": False,
            "gpu": None,
            "message": f"IC Flux Python probe timed out: {python_exe}",
            "install_hint": install_hint,
        }

    details: dict[str, Any] = {}
    try:
        details = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        pass
    missing = [str(item) for item in details.get("missing", [])]
    resolved_python = str(details.get("executable") or python_exe)
    if result.returncode == 0 and not missing:
        if not bool(details.get("cuda_available")):
            return {
                "ready": False,
                "python": resolved_python,
                "missing": [],
                "versions": details.get("versions", {}),
                "cuda_available": False,
                "gpu": details.get("gpu"),
                "message": "IC Flux Python has the required packages, but CUDA is not available to torch.",
                "install_hint": install_hint,
            }
        return {
            "ready": True,
            "python": resolved_python,
            "missing": [],
            "versions": details.get("versions", {}),
            "cuda_available": True,
            "gpu": details.get("gpu"),
            "message": "IC Flux Python runtime is ready.",
            "install_hint": "",
        }
    torchvision_error = str(details.get("torchvision_error", "")).strip()
    message = (
        f"IC Flux Python has an incompatible torch/torchvision install: {torchvision_error}"
        if torchvision_error
        else
        f"IC Flux Python runtime is missing packages: {', '.join(missing)}"
        if missing
        else (result.stderr or result.stdout or f"IC Flux Python probe failed with exit code {result.returncode}").strip()
    )
    return {
        "ready": False,
        "python": resolved_python,
        "missing": missing,
        "versions": details.get("versions", {}),
        "cuda_available": bool(details.get("cuda_available")),
        "gpu": details.get("gpu"),
        "message": message,
        "install_hint": install_hint,
    }


def _run_ic_flux_v2(inputs: PipelineInputs, output_dir: Path, config: PipelineConfig) -> tuple[np.ndarray, dict[str, Any]]:
    if os.environ.get("LATENT_MERGE_ENABLE_IC_FLUX") != "1":
        raise RuntimeError(
            "IC Flux v2 is an external GPU backend. Set LATENT_MERGE_ENABLE_IC_FLUX=1 after installing "
            "CUDA torch, diffusers, transformers, accelerate, and local weights under weights/ic-light-v2 "
            "and weights/flux1-dev. See scripts/run_ic_flux_comparison.sh."
        )

    repo_root = Path(__file__).resolve().parents[1]
    runner = repo_root / "scripts" / "ic_flux_runner.py"
    if not runner.is_file():
        runner = Path.cwd() / "scripts" / "ic_flux_runner.py"
    if not runner.is_file():
        raise RuntimeError(
            "IC Flux runner not found. Expected scripts/ic_flux_runner.py beside the app or bundled release."
        )

    python_exe = resolve_ic_flux_python()
    runtime = ic_flux_runtime_status(python_exe)
    if not runtime["ready"]:
        raise RuntimeError(
            "IC Flux Python runtime is not ready. "
            f"{runtime['message']}\n\nSet LATENT_MERGE_PYTHON to a Python environment with the IC Flux dependencies, or run:\n"
            f"{runtime['install_hint']}"
        )
    weights_dir = Path(os.environ.get("LATENT_MERGE_IC_FLUX_WEIGHTS", "weights/ic-light-v2"))
    flux_weights_dir = Path(os.environ.get("LATENT_MERGE_FLUX_WEIGHTS", "weights/flux1-dev"))
    ic_dir = output_dir / "ic_flux_v2_external"
    command = [
        python_exe,
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
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=60 * 30,
            env=_external_runner_env(),
        )
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
        "python": python_exe,
        "weights_dir": str(weights_dir),
        "flux_weights_dir": str(flux_weights_dir),
        "runner_stdout_tail": result.stdout[-2000:],
        "external_job": external_job,
    }


def run_pipeline(inputs: PipelineInputs, output_dir: Path, config: PipelineConfig) -> Path:
    t0 = time.perf_counter()
    start_rss_kb = _process_max_rss_kb()
    _reset_gpu_peak_memory()

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

    auxiliary_images: dict[str, np.ndarray] = {}

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
    elif config.backend == "latent_delta_proxy":
        model_adjusted_rgb, backend_report, auxiliary_images = _latent_delta_proxy(plate, cg_rgb, combined_alpha, config)
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
    for key in auxiliary_images:
        outputs[key] = output_dir / f"{key}.png"

    save_rgb(outputs["raw_a_over_b"], raw_a_over_b)
    save_rgba(outputs["adjusted_fg"], adjusted_rgb, combined_alpha)
    save_rgb(outputs["final_comp"], final_comp)
    save_rgb(outputs["delta"], delta_visual)
    save_rgb(outputs["alpha_weighted_delta"], alpha_weighted_delta_visual)
    save_alpha(outputs["alpha_used"], combined_alpha)
    save_alpha(outputs["correction_matte"], correction_matte)
    for key, image in auxiliary_images.items():
        if image.ndim == 3 and image.shape[2] == 1:
            save_alpha(outputs[key], image)
        else:
            save_rgb(outputs[key], image)

    job = {
        "schema": "latent-merge.phase1-run.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": _input_provenance(inputs),
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
            "latent_proposal_path": config.latent_proposal_path,
            "latent_delta_blur_px": config.latent_delta_blur_px,
            "latent_luma_strength": config.latent_luma_strength,
            "latent_color_strength": config.latent_color_strength,
            "latent_shadow_strength": config.latent_shadow_strength,
            "latent_shadow_offset_x": config.latent_shadow_offset_x,
            "latent_shadow_offset_y": config.latent_shadow_offset_y,
            "latent_shadow_blur_px": config.latent_shadow_blur_px,
            "latent_shadow_expand_px": config.latent_shadow_expand_px,
        },
        "inputs": {
            "plate_rgb": {"path": str(inputs.plate_rgb), "sha256": sha256_file(inputs.plate_rgb)},
            "cg_rgba": {"path": str(inputs.cg_rgba), "sha256": sha256_file(inputs.cg_rgba)},
            "alpha": {"path": str(inputs.alpha), "sha256": sha256_file(inputs.alpha)},
        },
        "outputs": {key: str(path) for key, path in outputs.items() if key != "job"},
        "backend_report": backend_report,
        "runtime": _runtime_telemetry(t0, start_rss_kb),
        "contract": {
            "plate_repainted": False,
            "primary_model_output": "adjusted foreground RGBA",
            "trusted_composite": "normal A-over-B over original plate",
            "interaction_passes": ["delta", "alpha_weighted_delta", "correction_matte"],
            "shadow_preview_applied_to_final_comp": False,
        },
    }
    outputs["job"].write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    return outputs["job"]
