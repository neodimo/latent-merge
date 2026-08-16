#!/usr/bin/env python3
"""Probe: can the existing identity check tell our two failure modes apart?

`scripts/assert_harmonization_output.py` gates foreground identity with
`identity_delta = mean(|adjusted - cg|)` inside alpha, upper-bounded by
`--max-identity-delta` (default 0.75).

This probe constructs three cases with known ground truth on the sh009 CG
foreground and asks whether that metric ranks them correctly:

  A  legitimate relight   -- global gain + warm tint; identity fully intact
  B  identity destroyed   -- structure blurred away, then mean/std re-matched
                             so global statistics look untouched
  C  neglect (no-op)      -- output identical to input

Run from the project root with the project venv.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

CG = "fixtures/compositingpro_sh009_minimal/cg_rgba.png"


def gradient_magnitude(img: np.ndarray) -> np.ndarray:
    acc = np.zeros(img.shape[:2], np.float32)
    for c in range(img.shape[-1]):
        gy, gx = np.gradient(img[..., c])
        acc += gx ** 2 + gy ** 2
    return np.sqrt(acc)


def main() -> None:
    cg = np.asarray(Image.open(CG).convert("RGBA"), np.float32) / 255.0
    rgb, alpha = cg[..., :3], cg[..., 3]
    mask = alpha > 0.05

    legit = np.clip(rgb * np.array([1.25, 1.10, 0.85]) * 0.85, 0, 1)

    dest = np.stack([gaussian_filter(rgb[..., c], 6.0) for c in range(3)], -1)
    for c in range(3):
        d, o = dest[..., c][mask], rgb[..., c][mask]
        dest[..., c] = np.clip(
            (dest[..., c] - d.mean()) * (o.std() / max(d.std(), 1e-6)) + o.mean(), 0, 1
        )

    neglect = rgb.copy()

    ref_grad = gradient_magnitude(rgb)[mask]

    def mean_abs_delta(x: np.ndarray) -> float:
        return float(np.abs(x[mask] - rgb[mask]).mean())

    def struct_corr(x: np.ndarray) -> float:
        return float(np.corrcoef(ref_grad, gradient_magnitude(x)[mask])[0, 1])

    print(f"mask px: {int(mask.sum())}")
    print(f"{'case':<24}{'mean_abs_delta':>16}{'grad_struct_corr':>18}")
    for name, img in [
        ("A legit relight", legit),
        ("B identity destroyed", dest),
        ("C neglect (no-op)", neglect),
    ]:
        print(f"{name:<24}{mean_abs_delta(img):>16.5f}{struct_corr(img):>18.4f}")


if __name__ == "__main__":
    main()
