#!/usr/bin/env python3
"""Three-axis bakeoff scorer for relight-backend candidates.

Declared before execution; see
`reports/model-landscape-20260816/BAKEOFF_PROTOCOL.md`.

  Axis 0  plate_untouched  -- binary pre-filter. Max abs delta between the
          final composite and the original plate, outside alpha. A candidate
          that fails is disqualified before anyone looks at an image.

  Axis 1  identity retained -- gradient-magnitude structure correlation inside
          alpha, adjusted foreground vs original CG. Blind to global gain and
          tint, sensitive to structure loss. Guards against Suppression.

  Axis 2  lighting changed  -- magnitude of change of the adjusted foreground
          against the raw A-over-B baseline, inside alpha. Guards against
          Neglect. A candidate under the floor is the control wearing a hat and
          must not enter the blind A/B.

This script REPORTS values. It deliberately does not declare pass/fail: run one
calibrates the thresholds. Axis 0 is the only binary, and it reuses the existing
Layer-1 tolerance convention from `scripts/phase2_rejection_checks.py`.

`--self-test` recovers known ground truth on constructed cases before any real
number is quoted. Per the 2026-08-15 finding, an unvalidated instrument is not
an instrument.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def load_rgba(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    return rgba[..., :3], rgba[..., 3]


def load_alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def gradient_magnitude(img: np.ndarray) -> np.ndarray:
    acc = np.zeros(img.shape[:2], np.float32)
    for c in range(img.shape[-1]):
        gy, gx = np.gradient(img[..., c])
        acc += gx ** 2 + gy ** 2
    return np.sqrt(acc)


def axis0_plate_untouched(plate: np.ndarray, final: np.ndarray,
                          alpha: np.ndarray, eps: float = 0.004) -> dict:
    outside = alpha <= eps
    if outside.sum() == 0:
        return {"max_abs_delta": None, "pixels": 0, "note": "no outside-alpha pixels"}
    delta = np.abs(final - plate).max(axis=-1)[outside]
    return {
        "max_abs_delta": float(delta.max()),
        "mean_abs_delta": float(delta.mean()),
        "pixels": int(outside.sum()),
    }


def axis1_identity(cg: np.ndarray, adjusted: np.ndarray, mask: np.ndarray) -> dict:
    ref = gradient_magnitude(cg)[mask]
    cand = gradient_magnitude(adjusted)[mask]
    corr = float(np.corrcoef(ref, cand)[0, 1])
    return {
        "grad_struct_corr": corr,
        "mean_abs_delta_legacy": float(np.abs(adjusted[mask] - cg[mask]).mean()),
    }


def axis2_change(raw_baseline: np.ndarray, candidate: np.ndarray,
                 mask: np.ndarray, core: np.ndarray | None = None) -> dict:
    """Change of the DELIVERABLE against the raw A-over-B baseline.

    Both arguments must be composites. Comparing an `adjusted_fg` foreground
    image against a composite baseline inflates the result at partial-alpha
    edge pixels, where the two are definitionally different: measured on
    sh009 that error was +62% (0.06534 vs 0.04046). Restricting to alpha>0.99
    made the two agree exactly, which is what identified the mistake.
    """
    d = candidate[mask] - raw_baseline[mask]
    out = {
        "mean_abs_change": float(np.abs(d).mean()),
        "rms_change": float(np.sqrt((d ** 2).mean())),
        "p95_abs_change": float(np.percentile(np.abs(d), 95)),
    }
    if core is not None and core.sum() > 0:
        dc = candidate[core] - raw_baseline[core]
        out["mean_abs_change_core_alpha"] = float(np.abs(dc).mean())
        out["core_alpha_pixels"] = int(core.sum())
    return out


def score(plate, cg, alpha, adjusted, final, raw_baseline, label, eps=0.004):
    mask = alpha > 0.05
    out = {
        "label": label,
        "mask_pixels": int(mask.sum()),
        "axis0_plate_untouched": axis0_plate_untouched(plate, final, alpha, eps),
        "axis1_identity": axis1_identity(cg, adjusted, mask),
    }
    # Axis 2 compares composite to composite: final_comp vs raw A-over-B.
    out["axis2_lighting_change"] = (
        axis2_change(raw_baseline, final, mask, core=alpha > 0.99)
        if raw_baseline is not None else None
    )
    return out


def self_test(cg_path: Path) -> dict:
    """Recover known ground truth on constructed cases."""
    from scipy.ndimage import gaussian_filter

    cg, alpha = load_rgba(cg_path)
    mask = alpha > 0.05

    legit = np.clip(cg * np.array([1.25, 1.10, 0.85]) * 0.85, 0, 1)

    dest = np.stack([gaussian_filter(cg[..., c], 6.0) for c in range(3)], -1)
    for c in range(3):
        d, o = dest[..., c][mask], cg[..., c][mask]
        dest[..., c] = np.clip(
            (dest[..., c] - d.mean()) * (o.std() / max(d.std(), 1e-6)) + o.mean(), 0, 1
        )

    cases = {"legit_relight": legit, "identity_destroyed": dest, "neglect_noop": cg.copy()}
    results = {}
    for name, img in cases.items():
        results[name] = {
            **axis1_identity(cg, img, mask),
            **axis2_change(cg, img, mask),
        }

    a1 = {k: v["grad_struct_corr"] for k, v in results.items()}
    a2 = {k: v["mean_abs_change"] for k, v in results.items()}
    checks = {
        "axis1_separates_destruction_from_legit":
            a1["legit_relight"] - a1["identity_destroyed"] > 0.5,
        "axis1_blind_to_global_gain": a1["legit_relight"] > 0.95,
        "axis2_flags_noop_as_zero": a2["neglect_noop"] < 1e-6,
        "axis2_nonzero_for_real_relight": a2["legit_relight"] > 1e-3,
    }
    return {"cases": results, "checks": checks, "all_passed": all(checks.values())}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--job", type=Path, help="pipeline job.json to score")
    p.add_argument("--fixture", type=Path,
                   default=Path("fixtures/compositingpro_sh009_minimal"))
    p.add_argument("--label", default=None)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--out", type=Path)
    args = p.parse_args()

    cg_path = args.fixture / "cg_rgba.png"

    if args.self_test:
        res = {"self_test": self_test(cg_path)}
    else:
        if not args.job:
            p.error("--job is required unless --self-test")
        job = json.loads(args.job.read_text())
        o = job["outputs"]
        plate = load_rgb(args.fixture / "plate_rgb.png")
        cg, _ = load_rgba(cg_path)
        alpha = load_alpha(Path(o["alpha_used"]))
        adjusted, _ = load_rgba(Path(o["adjusted_fg"]))
        final = load_rgb(Path(o["final_comp"]))
        raw = load_rgb(Path(o["raw_a_over_b"])) if "raw_a_over_b" in o else None
        label = args.label or job.get("config", {}).get("backend", "unknown")
        res = {
            "self_test": self_test(cg_path),
            "candidate": score(plate, cg, alpha, adjusted, final, raw, label),
        }

    text = json.dumps(res, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")


if __name__ == "__main__":
    main()
