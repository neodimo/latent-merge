from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


def _load_validator():
    path = Path("scripts/validate_photographic_fixtures.py")
    spec = importlib.util.spec_from_file_location("validate_photographic_fixtures_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fixture(root: Path, provenance: str = "photographic") -> Path:
    fixture = root / "case"
    fixture.mkdir()
    alpha = np.array([[0, 255], [64, 128]], dtype=np.uint8)
    Image.new("RGB", (2, 2), (20, 30, 40)).save(fixture / "plate_rgb.png")
    rgba = np.dstack(
        [
            np.full((2, 2), 100, dtype=np.uint8),
            np.full((2, 2), 110, dtype=np.uint8),
            np.full((2, 2), 120, dtype=np.uint8),
            alpha,
        ]
    )
    Image.fromarray(rgba, "RGBA").save(fixture / "cg_rgba.png")
    Image.fromarray(alpha, "L").save(fixture / "alpha.png")
    hashes = {}
    for name in ("plate_rgb.png", "cg_rgba.png", "alpha.png"):
        hashes[name] = hashlib.sha256((fixture / name).read_bytes()).hexdigest()[:16]
    (fixture / "fixture.json").write_text(
        json.dumps(
            {
                "plate_provenance": provenance,
                "source": "test source",
                "license": "test license",
                "tonemap": "test transform",
                "files": hashes,
            }
        ),
        encoding="utf-8",
    )
    return fixture


class ValidatePhotographicFixturesTest(unittest.TestCase):
    def test_accepts_complete_fixture(self) -> None:
        validator = _load_validator()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_fixture(Path(tmp))
            result = validator.validate_fixture(fixture)
        self.assertTrue(result["ok"], result["errors"])

    def test_rejects_hash_and_alpha_mismatch(self) -> None:
        validator = _load_validator()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _write_fixture(Path(tmp))
            Image.new("L", (2, 2), 255).save(fixture / "alpha.png")
            result = validator.validate_fixture(fixture)
        self.assertFalse(result["ok"])
        self.assertTrue(any("degenerate" in error for error in result["errors"]))
        self.assertTrue(any("hash mismatch" in error for error in result["errors"]))

    def test_minimum_count_fails_closed(self) -> None:
        validator = _load_validator()
        with tempfile.TemporaryDirectory() as tmp:
            _write_fixture(Path(tmp))
            result = validator.validate_root(Path(tmp), min_count=5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["photographic_fixture_count"], 1)
        self.assertIn("below required minimum 5", result["errors"][0])

    def test_ignores_non_photographic_fixture_for_count(self) -> None:
        validator = _load_validator()
        with tempfile.TemporaryDirectory() as tmp:
            _write_fixture(Path(tmp), provenance="synthetic")
            result = validator.validate_root(Path(tmp), min_count=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["photographic_fixture_count"], 0)

    def test_malformed_manifest_fails_closed_without_crashing(self) -> None:
        validator = _load_validator()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "broken"
            fixture.mkdir()
            (fixture / "fixture.json").write_text("{not json", encoding="utf-8")
            result = validator.validate_root(Path(tmp), min_count=0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["photographic_fixture_count"], 0)
        self.assertTrue(any("invalid fixture.json" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
