from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import phase2_rejection_checks


def _save_rgb(path: Path, value: int = 128) -> None:
    data = np.full((4, 4, 3), value, dtype=np.uint8)
    Image.fromarray(data, mode="RGB").save(path)


def _save_alpha(path: Path) -> None:
    data = np.full((4, 4), 255, dtype=np.uint8)
    Image.fromarray(data, mode="L").save(path)


def _write_job(fixture_dir: Path, run_dir: Path) -> Path:
    plate = fixture_dir / "plate_rgb.png"
    cg = fixture_dir / "cg_rgba.png"
    alpha = fixture_dir / "alpha.png"
    final_comp = run_dir / "final_comp.png"
    raw = run_dir / "raw_a_over_b.png"
    alpha_used = run_dir / "alpha_used.png"
    for path in (plate, cg, final_comp, raw):
        _save_rgb(path)
    _save_alpha(alpha)
    _save_alpha(alpha_used)

    job = {
        "inputs": {
            "plate_rgb": {"path": str(plate)},
            "cg_rgba": {"path": str(cg)},
            "alpha": {"path": str(alpha)},
        },
        "outputs": {
            "raw_a_over_b": str(raw),
            "final_comp": str(final_comp),
            "alpha_used": str(alpha_used),
        },
        "runtime": {
            "duration_s": 1.0,
            "process_max_rss_mb": 128.0,
            "gpu_memory": {"cuda_available": False},
        },
        "contract": {"plate_repainted": False},
    }
    job_path = run_dir / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    return job_path


class Phase2RejectionChecksTest(unittest.TestCase):
    def test_non_photographic_fixture_fails_quality_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "fixtures" / "smoke_case"
            run_dir = root / "runs" / "smoke_case"
            fixture_dir.mkdir(parents=True)
            run_dir.mkdir(parents=True)
            (fixture_dir / "fixture.json").write_text(
                json.dumps({"plate_provenance": "synthetic"}),
                encoding="utf-8",
            )

            job_path = _write_job(fixture_dir, run_dir)
            result = phase2_rejection_checks.run(job_path, {
                "plate_untouched": {"alpha_zero_eps": 0.004, "max_abs_delta": 0.012},
                "edge_seam": {
                    "alpha_low": 0.05,
                    "alpha_high": 0.95,
                    "dilate_px": 2,
                    "max_grad_ratio": 1.25,
                },
                "runtime": {
                    "max_duration_s": 30.0,
                    "max_process_rss_mb": 11000.0,
                    "max_reserved_vram_mb": 11000.0,
                },
                "flicker": {"max_final_comp_temporal_rmse": 0.05},
            }, None)

            self.assertFalse(result["overall_pass"])
            self.assertEqual(result["plate_provenance"], "synthetic")
            provenance_check = next(
                check for check in result["checks"]
                if check["check"] == "plate_provenance_photographic"
            )
            self.assertFalse(provenance_check["pass"])


if __name__ == "__main__":
    unittest.main()
