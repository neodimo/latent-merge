"""Assembler must emit fixtures the photographic validator accepts as-is.

These tests prove the plate->fixture->validator-clean chain end to end without
producing a counted photographic fixture in the repo: everything runs in a tmp
dir, so DiMo's L1 ruling is not front-run.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.assemble_fixture import assemble
from scripts.validate_photographic_fixtures import validate_fixture


def _write_plate(path: Path, wh=(320, 200)) -> Path:
    w, h = wh
    # Non-constant plate so nothing downstream is degenerate.
    grad = np.linspace(0, 255, w, dtype=np.uint8)
    plate = np.repeat(grad[None, :], h, axis=0)
    rgb = np.stack([plate, plate[:, ::-1], np.full_like(plate, 128)], axis=-1)
    Image.fromarray(rgb, mode="RGB").save(path)
    return path


def _extraction_manifest(path: Path, provenance="photographic") -> Path:
    path.write_text(
        json.dumps(
            {
                "plate_provenance": provenance,
                "source": "Poly Haven - test_pano (CC0)",
                "license": "CC0",
                "tonemap": "panorama LDR/tonemapped as provided; HDRI used for relight",
                "source_url": "https://example.invalid/test_pano",
                "matched_hdri": "test_pano.jpg",
                "view": {"yaw_deg": 0.0, "pitch_deg": -5.0, "hfov_deg": 75.0},
            }
        ),
        encoding="utf-8",
    )
    return path


class TestAssembleFixture(unittest.TestCase):
    def test_placeholder_fixture_passes_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plate = _write_plate(tmp / "plate_rgb.png")
            man = _extraction_manifest(tmp / "plate_extraction.json")
            out = tmp / "fixture"
            assemble(plate, out, fixture_id="test_001", extraction_manifest=man)

            result = validate_fixture(out)
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(result["dimensions_wh"], [320, 200])

    def test_provenance_and_metadata_carried_from_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plate = _write_plate(tmp / "plate_rgb.png")
            man = _extraction_manifest(tmp / "plate_extraction.json")
            out = tmp / "fixture"
            m = assemble(plate, out, fixture_id="test_002", extraction_manifest=man)
            self.assertEqual(m["plate_provenance"], "photographic")
            self.assertEqual(m["license"], "CC0")
            self.assertFalse(m["cg_insert_is_quality_bearing"])
            self.assertIn("matched_hdri", m["plate_extraction"])

    def test_alpha_matches_cg_alpha_channel_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plate = _write_plate(tmp / "plate_rgb.png")
            man = _extraction_manifest(tmp / "plate_extraction.json")
            out = tmp / "fixture"
            assemble(plate, out, fixture_id="test_003", extraction_manifest=man)
            cg = np.asarray(Image.open(out / "cg_rgba.png").convert("RGBA"))
            alpha = np.asarray(Image.open(out / "alpha.png").convert("L"))
            self.assertTrue(np.array_equal(cg[..., 3], alpha))

    def test_refuses_to_stamp_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plate = _write_plate(tmp / "plate_rgb.png")
            out = tmp / "fixture"
            with self.assertRaises(ValueError):
                assemble(plate, out, fixture_id="test_004")  # no manifest, no flags

    def test_supplied_cg_is_marked_quality_bearing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plate = _write_plate(tmp / "plate_rgb.png", wh=(320, 200))
            man = _extraction_manifest(tmp / "plate_extraction.json")
            # A real-ish CG render at full plate size with a non-degenerate matte.
            cg = np.zeros((200, 320, 4), dtype=np.uint8)
            cg[60:140, 100:220, :3] = (200, 120, 60)
            cg[60:140, 100:220, 3] = 255
            cg_path = tmp / "cg.png"
            Image.fromarray(cg, mode="RGBA").save(cg_path)
            out = tmp / "fixture"
            m = assemble(plate, out, fixture_id="test_005", cg_path=cg_path, extraction_manifest=man)
            self.assertTrue(m["cg_insert_is_quality_bearing"])
            self.assertTrue(validate_fixture(out)["ok"])


if __name__ == "__main__":
    unittest.main()
