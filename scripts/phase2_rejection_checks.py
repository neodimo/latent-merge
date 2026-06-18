#!/usr/bin/env python3
"""Phase 2 Layer-1 automated hard-rejection checks.

Given a pipeline job directory (with job.json + the standard output family),
run the objective pass/fail checks that gate a harmonization result before any
human/visual scoring:

  - plate_untouched : pixels outside the matte must equal the original plate
                      (the core trust contract). A failure here is a hard
                      trust-contract violation.
  - edge_seam       : the matte edge must not gain halos/seams beyond the raw
                      A-over-B composite (heuristic gradient-energy guard).
  - plate_provenance: quality-gate jobs must use photographic plates.
  - runtime         : duration / process RSS / reserved VRAM stay under ceilings.
  - flicker         : sequence cases only; max temporal RMSE under ceiling
                      (consumes sequence_metrics.json).

This is Layer 1 of the Phase 2 gate. It does NOT judge whether a result looks
well integrated; that is Layer 2 (blind A/B visual scoring). See PHASE2_GATE.md.

Usage:
  PYTHONPATH=".deps:." python3 scripts/phase2_rejection_checks.py \
      --job runs/<case>/job.json \
      [--sequence-metrics runs/<case>/sequence_metrics.json] \
      [--config configs/phase2_gate.json] \
      [--out runs/<case>/rejection_checks.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "phase2_gate.json"


def _load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def _load_alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def _resolve(path_str: str, job_dir: Path, prefer_local: bool = False) -> Path:
    """Resolve a path recorded in job.json.

    For outputs (prefer_local=True) the file that physically lives in the job
    dir is authoritative: job.json may record an absolute path to the original
    run location, but the gate evaluates the artifacts in *this* job dir, so a
    co-located basename must win. For inputs (fixtures elsewhere) the recorded
    path is tried first.
    """
    p = Path(path_str)
    by_name = job_dir / p.name
    candidates = [by_name, p, ROOT / path_str] if prefer_local else [p, by_name, ROOT / path_str]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"Could not resolve {path_str} (job_dir={job_dir})")


def _metadata_from_path(path: Path, stop_at: Path = ROOT) -> tuple[Path, dict[str, Any]] | None:
    """Find fixture metadata near an input path.

    Fixture roots use fixture.json; the Blender smoke set currently uses
    manifest.json. Old report jobs may contain copied inputs with no nearby
    metadata, so callers must fail closed when this returns None.
    """
    try:
        resolved = path.resolve()
    except FileNotFoundError:
        resolved = path
    search_roots = [resolved.parent if resolved.suffix else resolved]
    search_roots.extend(search_roots[0].parents)
    try:
        stop = stop_at.resolve()
    except FileNotFoundError:
        stop = stop_at

    for directory in search_roots:
        for name in ("fixture.json", "manifest.json"):
            candidate = directory / name
            if candidate.is_file():
                return candidate, json.loads(candidate.read_text(encoding="utf-8"))
        if directory == stop:
            break
    return None


def resolve_plate_provenance(job: dict[str, Any], inputs: dict[str, Any], job_dir: Path) -> dict[str, Any]:
    recorded = job.get("plate_provenance")
    if isinstance(recorded, str):
        return {"plate_provenance": recorded, "source": "job.plate_provenance"}

    provenance = job.get("provenance", {})
    if isinstance(provenance, dict) and isinstance(provenance.get("plate_provenance"), str):
        return {
            "plate_provenance": provenance["plate_provenance"],
            "source": "job.provenance.plate_provenance",
        }

    plate_info = inputs.get("plate_rgb", {})
    if not isinstance(plate_info, dict) or "path" not in plate_info:
        return {"plate_provenance": "unknown", "source": "missing inputs.plate_rgb.path"}

    plate_path = _resolve(plate_info["path"], job_dir)
    metadata = _metadata_from_path(plate_path)
    if metadata is None:
        return {
            "plate_provenance": "unknown",
            "source": f"no fixture metadata near {plate_path}",
        }
    metadata_path, payload = metadata
    value = payload.get("plate_provenance", "unknown")
    return {
        "plate_provenance": value if isinstance(value, str) else "unknown",
        "source": str(metadata_path),
    }


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _grad_mag(gray: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(gray)
    return np.sqrt(gx * gx + gy * gy)


def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask
    out = mask.copy()
    for _ in range(px):
        shifted = out.copy()
        shifted[1:, :] |= out[:-1, :]
        shifted[:-1, :] |= out[1:, :]
        shifted[:, 1:] |= out[:, :-1]
        shifted[:, :-1] |= out[:, 1:]
        out = shifted
    return out


def _check(name: str, value: Any, threshold: Any, passed: bool, **extra: Any) -> dict[str, Any]:
    rec = {"check": name, "value": value, "threshold": threshold, "pass": bool(passed)}
    rec.update(extra)
    return rec


def check_plate_untouched(plate: np.ndarray, final_comp: np.ndarray, alpha: np.ndarray,
                          cfg: dict[str, Any]) -> dict[str, Any]:
    eps = float(cfg["alpha_zero_eps"])
    tol = float(cfg["max_abs_delta"])
    mask = alpha <= eps
    if not mask.any():
        return _check("plate_untouched", None, tol, True, skipped=True,
                      reason="no fully-outside-matte pixels")
    delta = np.abs(final_comp - plate).max(axis=-1)
    max_delta = float(delta[mask].max())
    mean_delta = float(delta[mask].mean())
    return _check("plate_untouched", round(max_delta, 5), tol, max_delta <= tol,
                  mean_abs_delta=round(mean_delta, 5),
                  pixels_checked=int(mask.sum()))


def check_edge_seam(raw_over: np.ndarray, final_comp: np.ndarray, alpha: np.ndarray,
                    cfg: dict[str, Any]) -> dict[str, Any]:
    lo, hi = float(cfg["alpha_low"]), float(cfg["alpha_high"])
    band = _dilate((alpha > lo) & (alpha < hi), int(cfg["dilate_px"]))
    if not band.any():
        return _check("edge_seam", None, cfg["max_grad_ratio"], True, skipped=True,
                      reason="no partial-alpha edge band")
    g_final = _grad_mag(_luma(final_comp))
    g_raw = _grad_mag(_luma(raw_over))
    raw_energy = float(g_raw[band].mean())
    final_energy = float(g_final[band].mean())
    ratio = final_energy / raw_energy if raw_energy > 1e-6 else 1.0
    thr = float(cfg["max_grad_ratio"])
    return _check("edge_seam", round(ratio, 4), thr, ratio <= thr,
                  raw_edge_energy=round(raw_energy, 5),
                  final_edge_energy=round(final_energy, 5),
                  band_pixels=int(band.sum()))


def check_runtime(runtime: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dur = runtime.get("duration_s")
    if isinstance(dur, (int, float)):
        thr = float(cfg["max_duration_s"])
        out.append(_check("runtime_duration_s", round(float(dur), 4), thr, dur <= thr))
    rss = runtime.get("process_max_rss_mb")
    if isinstance(rss, (int, float)):
        thr = float(cfg["max_process_rss_mb"])
        out.append(_check("runtime_process_rss_mb", round(float(rss), 2), thr, rss <= thr))
    gpu = runtime.get("gpu_memory", {}) or {}
    if gpu.get("cuda_available"):
        vram = gpu.get("max_reserved_mb") or gpu.get("max_allocated_mb") or 0.0
        thr = float(cfg["max_reserved_vram_mb"])
        out.append(_check("runtime_reserved_vram_mb", round(float(vram), 2), thr, vram <= thr))
    return out


def check_evidence_complete(outputs: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when a job lacks evidence required by the Layer-1 gate."""
    missing: list[str] = []
    if "raw_a_over_b" not in outputs:
        missing.append("outputs.raw_a_over_b")
    if not isinstance(runtime.get("duration_s"), (int, float)):
        missing.append("runtime.duration_s")
    if not isinstance(runtime.get("process_max_rss_mb"), (int, float)):
        missing.append("runtime.process_max_rss_mb")

    gpu = runtime.get("gpu_memory", {}) or {}
    has_vram = isinstance(gpu.get("max_reserved_mb"), (int, float)) or isinstance(
        gpu.get("max_allocated_mb"), (int, float)
    )
    if gpu.get("cuda_available") and not has_vram:
        missing.append("runtime.gpu_memory.max_reserved_mb")

    return _check(
        "gate_evidence_complete",
        len(missing),
        0,
        not missing,
        missing=missing,
    )


def check_plate_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    value = provenance["plate_provenance"]
    return _check(
        "plate_provenance_photographic",
        value,
        "photographic",
        value == "photographic",
        source=provenance["source"],
    )


def check_flicker(metrics_path: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    value = (data.get("max_final_comp_temporal_rmse")
             or data.get("final_comp", {}).get("max_temporal_rmse"))
    thr = float(cfg["max_final_comp_temporal_rmse"])
    if value is None:
        return _check("flicker_final_comp_rmse", None, thr, True, skipped=True,
                      reason="no temporal rmse field in sequence metrics")
    return _check("flicker_final_comp_rmse", round(float(value), 5), thr, float(value) <= thr)


def run(job_path: Path, config: dict[str, Any], sequence_metrics: Path | None) -> dict[str, Any]:
    job_dir = job_path.parent if job_path.is_file() else job_path
    if job_path.is_dir():
        job_path = job_path / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))

    inputs = job.get("inputs", {})
    outputs = job.get("outputs", {})
    provenance = resolve_plate_provenance(job, inputs, job_dir)
    plate = _load_rgb(_resolve(inputs["plate_rgb"]["path"], job_dir))
    if "alpha_used" in outputs:
        alpha = _load_alpha(_resolve(outputs["alpha_used"], job_dir, prefer_local=True))
    else:
        alpha = _load_alpha(_resolve(inputs["alpha"]["path"], job_dir))
    final_comp = _load_rgb(_resolve(outputs["final_comp"], job_dir, prefer_local=True))

    checks: list[dict[str, Any]] = []
    runtime = job.get("runtime", {}) or {}
    checks.append(check_evidence_complete(outputs, runtime))
    checks.append(check_plate_provenance(provenance))
    checks.append(check_plate_untouched(plate, final_comp, alpha, config["plate_untouched"]))

    if "raw_a_over_b" in outputs:
        raw_over = _load_rgb(_resolve(outputs["raw_a_over_b"], job_dir, prefer_local=True))
        checks.append(check_edge_seam(raw_over, final_comp, alpha, config["edge_seam"]))

    checks.extend(check_runtime(runtime, config["runtime"]))

    if sequence_metrics and sequence_metrics.is_file():
        checks.append(check_flicker(sequence_metrics, config["flicker"]))

    # Trust-contract violation: plate repainted, or plate_untouched failed.
    contract = job.get("contract", {})
    plate_check = next((c for c in checks if c["check"] == "plate_untouched"), None)
    trust_violation = bool(contract.get("plate_repainted")) or (
        plate_check is not None and not plate_check["pass"] and not plate_check.get("skipped")
    )

    applicable = [c for c in checks if not c.get("skipped")]
    overall_pass = all(c["pass"] for c in applicable) and not trust_violation

    return {
        "schema": "latent-merge.phase2-rejection.v1",
        "job": str(job_path),
        "overall_pass": overall_pass,
        "trust_contract_violation": trust_violation,
        "checks_passed": sum(1 for c in applicable if c["pass"]),
        "checks_applicable": len(applicable),
        "plate_provenance": provenance["plate_provenance"],
        "plate_provenance_source": provenance["source"],
        "checks": checks,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 2 Layer-1 hard-rejection checks")
    ap.add_argument("--job", required=True, help="job.json or its directory")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--sequence-metrics", default=None,
                    help="sequence_metrics.json for sequence cases")
    ap.add_argument("--out", default=None, help="write result JSON here (default: next to job)")
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    seq = Path(args.sequence_metrics) if args.sequence_metrics else None
    result = run(Path(args.job), config, seq)

    out_path = Path(args.out) if args.out else (
        (Path(args.job).parent if Path(args.job).is_file() else Path(args.job)) / "rejection_checks.json")
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    status = "PASS" if result["overall_pass"] else "FAIL"
    print(f"[{status}] {result['checks_passed']}/{result['checks_applicable']} checks "
          f"(trust_violation={result['trust_contract_violation']}) -> {out_path}")
    for c in result["checks"]:
        flag = "skip" if c.get("skipped") else ("ok" if c["pass"] else "FAIL")
        print(f"  [{flag:4}] {c['check']}: value={c['value']} thr={c['threshold']}")
    sys.exit(0 if result["overall_pass"] else 1)


if __name__ == "__main__":
    main()
