#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


REQUIRED_METADATA = ("source", "license", "tonemap")
REQUIRED_FILES = ("plate_rgb.png", "cg_rgba.png", "alpha.png")


def _sha256_prefix(path: Path, length: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def validate_fixture(fixture_dir: Path) -> dict[str, Any]:
    manifest_path = fixture_dir / "fixture.json"
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"fixture": str(fixture_dir), "ok": False, "errors": [f"invalid fixture.json: {error}"]}

    if manifest.get("plate_provenance") != "photographic":
        errors.append("plate_provenance must be photographic")

    for key in REQUIRED_METADATA:
        value = manifest.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing non-empty metadata: {key}")

    paths = {name: fixture_dir / name for name in REQUIRED_FILES}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"missing required file: {name}")
    if any(not path.is_file() for path in paths.values()):
        return {"fixture": str(fixture_dir), "ok": False, "errors": errors}

    try:
        plate = np.asarray(Image.open(paths["plate_rgb.png"]).convert("RGB"))
        cg = np.asarray(Image.open(paths["cg_rgba.png"]).convert("RGBA"))
        alpha = np.asarray(Image.open(paths["alpha.png"]).convert("L"))
    except (OSError, ValueError) as error:
        errors.append(f"unreadable image: {error}")
        return {"fixture": str(fixture_dir), "ok": False, "errors": errors}

    shape = plate.shape[:2]
    if cg.shape[:2] != shape or alpha.shape != shape:
        errors.append(
            f"dimension mismatch: plate={plate.shape[:2]} cg={cg.shape[:2]} alpha={alpha.shape}"
        )
    if alpha.min() == alpha.max():
        errors.append("alpha.png is degenerate (constant)")
    if cg.shape[:2] == alpha.shape:
        alpha_delta = float(np.abs(cg[..., 3].astype(np.int16) - alpha.astype(np.int16)).max())
        if alpha_delta > 1:
            errors.append(f"cg_rgba alpha differs from alpha.png (max delta={alpha_delta:.0f}/255)")

    recorded_files = manifest.get("files")
    if not isinstance(recorded_files, dict):
        errors.append("missing files hash map")
    else:
        for name, path in paths.items():
            recorded = recorded_files.get(name)
            if not isinstance(recorded, str) or len(recorded) < 8:
                errors.append(f"missing hash prefix for {name}")
                continue
            actual = _sha256_prefix(path, len(recorded))
            if actual != recorded.lower():
                errors.append(f"hash mismatch for {name}: expected {recorded}, got {actual}")

    return {
        "fixture": str(fixture_dir),
        "ok": not errors,
        "dimensions_wh": [int(shape[1]), int(shape[0])],
        "errors": errors,
    }


def validate_root(fixtures_root: Path, min_count: int = 1) -> dict[str, Any]:
    fixture_dirs: list[Path] = []
    discovery_errors: list[str] = []
    for manifest_path in sorted(fixtures_root.glob("*/fixture.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            discovery_errors.append(f"{manifest_path}: invalid fixture.json: {error}")
            continue
        if manifest.get("plate_provenance") == "photographic":
            fixture_dirs.append(manifest_path.parent)

    results = [validate_fixture(path) for path in fixture_dirs]
    errors = list(discovery_errors)
    plate_hash_to_fixtures: dict[str, list[str]] = {}
    for fixture_dir, result in zip(fixture_dirs, results):
        if not result["ok"]:
            continue
        plate_hash = _sha256_prefix(fixture_dir / "plate_rgb.png", 64)
        plate_hash_to_fixtures.setdefault(plate_hash, []).append(str(fixture_dir))
    duplicate_plate_groups = [
        fixtures for fixtures in plate_hash_to_fixtures.values() if len(fixtures) > 1
    ]
    unique_count = len(plate_hash_to_fixtures)
    if duplicate_plate_groups:
        for fixtures in duplicate_plate_groups:
            errors.append(f"duplicate photographic plate across fixtures: {', '.join(fixtures)}")
    if unique_count < min_count:
        errors.append(
            f"unique photographic fixture count {unique_count} is below required minimum {min_count}"
        )
    if any(not result["ok"] for result in results):
        errors.append("one or more photographic fixtures failed validation")
    return {
        "ok": not errors,
        "photographic_fixture_count": len(results),
        "unique_photographic_fixture_count": unique_count,
        "minimum_required": min_count,
        "fixtures": results,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate locked photographic eval fixtures.")
    parser.add_argument("--fixtures-root", type=Path, default=Path("fixtures"))
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_root(args.fixtures_root, args.min_count)
    rendered = json.dumps(report, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
