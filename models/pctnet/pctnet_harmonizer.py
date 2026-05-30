"""
PCT-Net direct inference harness.
Wraps the Rakuten PCT-Net model so it can be called as a backend in core/pipeline.py.
Takes composite RGB float32 0-1 + alpha float32 0-1 (both HxWx3/HxWx1), returns harmonized RGB 0-1.

No libcom dependency — imports only torch, cv2, numpy, pathlib.
"""
from __future__ import annotations

import torch
import cv2
import numpy as np
from pathlib import Path
from typing import Optional


# ImageNet normalization constants
_MEAN = torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32)
_STD  = torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32)
_DIVISOR = 8


def _detect_tier() -> str:
    """Auto-detect VRAM tier from nvidia-smi. Returns compact-8 / mid-16 / full-48."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        vram_mb = int(result.stdout.strip().split("\n")[0])
    except Exception:
        return "mid-16"
    if vram_mb >= 45000:
        return "full-48"
    elif vram_mb >= 14336:
        return "mid-16"
    else:
        return "compact-8"


def _pad_to_divisor(image: np.ndarray, mask: np.ndarray, divisor: int = _DIVISOR):
    """Pad image and mask so H,W are divisible by divisor."""
    pad_h = (divisor - image.shape[0] % divisor) % divisor
    pad_w = (divisor - image.shape[1] % divisor) % divisor
    top, bottom = pad_h // 2, pad_h - pad_h // 2
    left, right = pad_w // 2, pad_w - pad_w // 2
    image_padded = cv2.copyMakeBorder(image, top, bottom, left, right,
                                     cv2.BORDER_CONSTANT, value=0)
    mask_padded = cv2.copyMakeBorder(mask, top, bottom, left, right,
                                     cv2.BORDER_CONSTANT, value=0)
    return image_padded, mask_padded, (top, bottom, left, right)


def _remove_padding(image: np.ndarray, pads: tuple):
    top, bottom, left, right = pads
    return image[top:image.shape[0]-bottom, left:image.shape[1]-right]


class PCTNetHarmonizer:
    """
    Loads PCTNet_CNN from disk and applies it to a composite image.
    Device is auto-detected (cuda first, cpu fallback).

    Tier controls precision:
      - "compact-8"  → fp16 inference (8 GB VRAM)
      - "mid-16"     → fp32 inference (16+ GB VRAM)
      - "full-48"    → fp32 inference (48+ GB VRAM)
      - None/""      → auto-detect via nvidia-smi or fp32 fallback
    """

    def __init__(self, weight_path: str | Path, device: Optional[str] = None,
                 tier: Optional[str] = None):
        self.weight_path = Path(weight_path)
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        ) if device is None else torch.device(device)
        self.tier = tier or _detect_tier()
        self._fp16 = self.tier == "compact-8" and self.device.type == "cuda"

        import sys
        iharm_root = self.weight_path.parent / "iharm"
        sys.path.insert(0, str(self.weight_path.parent))
        sys.path.insert(0, str(iharm_root.parent))
        sys.path.insert(0, str(iharm_root))

        from iharm.mconfigs import ALL_MCONFIGS
        from iharm.inference.utils import load_model

        self._net = load_model("CNN_pct", str(self.weight_path), verbose=True)
        self._net = self._net.to(self.device)
        if self._fp16:
            self._net = self._net.half()
        self._net.eval()

    @torch.no_grad()
    def harmonize(self, fg_rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
        """
        Args
        ----
        fg_rgb : float32 HxWx3, values 0-1 — CG foreground only (no plate pixels)
        alpha  : float32 HxWxC or HxWx1, values 0-1 (white = foreground)

        Returns
        -------
        harmonized_rgb : float32 HxWx3, values 0-1
        """
        if alpha.ndim == 3:
            alpha = alpha[..., 0]
        alpha = alpha.clip(0, 1)

        fg8 = np.clip(fg_rgb, 0, 1).astype(np.uint8)
        mask8 = (alpha * 255).astype(np.uint8)

        comp_pad, mask_pad, pads = _pad_to_divisor(fg8, mask8)

        dtype = torch.float16 if self._fp16 else torch.float32
        mean3 = _MEAN.to(self.device, dtype=dtype).reshape(3, 1, 1)
        std3  = _STD.to(self.device, dtype=dtype).reshape(3, 1, 1)

        # Full-res normalized image: HxWx3 -> 1x3xHxW
        img_t = (torch.as_tensor(comp_pad, dtype=dtype, device=self.device)
                     .permute(2, 0, 1).unsqueeze(0) / 255.0)
        img_norm = (img_t - mean3.reshape(1, 3, 1, 1)) / std3.reshape(1, 3, 1, 1)

        # Mask: HxW -> 1x1xHxW
        msk_t = (torch.as_tensor(mask_pad, dtype=dtype, device=self.device)
                     .unsqueeze(0).unsqueeze(0) / 255.0)

        # Low-res branches
        lowres_norm = torch.nn.functional.interpolate(
            img_norm, scale_factor=0.5, mode="bilinear", align_corners=False)
        lowres_msk  = torch.nn.functional.interpolate(
            msk_t, scale_factor=0.5, mode="nearest")

        output = self._net(lowres_norm, img_norm, lowres_msk, msk_t)

        # images_fullres: 3xHxW (C=3, H, W). Already denormalized via ImageNet mean/std.
        raw = output.get("images_fullres", output["images"])
        if raw.dim() == 4:
            raw = raw.squeeze(0)                          # 1x3xHxW -> 3xHxW
        result = raw.permute(1, 2, 0).clamp(0, 255)       # 3xHxW -> HxWx3 on CUDA

        result_hwc = result.to(dtype=torch.float32).cpu().numpy()
        result_hwc = _remove_padding(result_hwc, pads)

        return result_hwc.astype(np.float32) / 255.0


def harmonize_image_pctnet(
    fg_rgb: np.ndarray,
    alpha: np.ndarray,
    weight_path: str | Path,
    device: Optional[str] = None,
    tier: Optional[str] = None,
) -> np.ndarray:
    """One-shot PCT-Net harmonization entrypoint for core/pipeline.py."""
    return PCTNetHarmonizer(weight_path, device=device, tier=tier).harmonize(fg_rgb, alpha)
