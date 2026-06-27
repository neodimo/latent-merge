#!/usr/bin/env python3
"""Assemble a validator-clean eval fixture from a photographic plate.

This is the step `pano_to_plate.py` deliberately stops short of. Given a plate
(`plate_rgb.png`) plus its extraction manifest, this writes a complete fixture
directory -- `plate_rgb.png` / `cg_rgba.png` / `alpha.png` / `fixture.json` --
that satisfies `validate_photographic_fixtures.py` exactly: provenance carried
from the plate, required metadata present, the CG alpha channel byte-identical
to `alpha.png`, dimensions matched, and a `files` hash map computed the same way
the validator recomputes it.

CG insert sourcing is explicit and honest:

  * `--cg` supplies a real RGBA CG render (e.g. a 3D object lit by the matched
    HDRI). This is what a genuine L1 photographic fixture must use.
  * with no `--cg`, a procedural shaded-sphere placeholder is generated. The
    placeholder exercises and proves the assembler contract; it is NOT a
    quality-bearing CG insert and must not be used for a counted L1 fixture.

Provenance is carried from the plate, never invented. Stamping a fixture
`photographic` is only honest when the plate truly is -- this tool does not
upgrade a synthetic plate to photographic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


REQUIRED_METADATA = ("source", "license", "tonemap")


def _sha256_prefix(path: Path, length: int = 16) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def procedural_cg_insert(plate_wh: tuple[int, int]) -> np.ndarray:
    """A center-placed shaded sphere with a soft anti-aliased alpha matte.

    Returns an H x W x 4 uint8 RGBA array sized to the plate. This is plumbing
    only: it gives the assembler a non-degenerate alpha and a believable RGB so
    the validator contract can be exercised without a real render.
    """
    w, h = plate_wh
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    cx, cy = w / 2.0, h * 0.58
    radius = min(w, h) * 0.18
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

    # Soft 1.5px edge so the matte is anti-aliased, not a hard step.
    alpha = np.clip((radius - dist) / 1.5 + 0.5, 0.0, 1.0)

    # Lambert-ish shading from an up-left key so RGB has structure.
    nx = np.clip((cx - xx) / radius, -1.0, 1.0)
    ny = np.clip((cy - yy) / radius, -1.0, 1.0)
    nz = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
    light = np.array([-0.5, -0.6, 0.62])
    light = light / np.linalg.norm(light)
    lambert = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0.05, 1.0)
    base = np.array([0.80, 0.45, 0.30])  # warm clay
    rgb = np.clip(base[None, None, :] * lambert[..., None] * 255.0, 0, 255)

    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = np.rint(rgb).astype(np.uint8)
    out[..., 3] = np.rint(alpha * 255.0).astype(np.uint8)
    return out


def _load_cg(cg_path: Path, plate_wh: tuple[int, int]) -> np.ndarray:
    cg = np.asarray(Image.open(cg_path).convert("RGBA"))
    if (cg.shape[1], cg.shape[0]) != plate_wh:
        raise ValueError(
            f"--cg size {(cg.shape[1], cg.shape[0])} must match plate size {plate_wh}; "
            "pre-composite the CG onto a full-plate-size RGBA canvas first"
        )
    return cg


def assemble(
    plate_path: Path,
    out_dir: Path,
    *,
    fixture_id: str,
    cg_path: Path | None = None,
    extraction_manifest: Path | None = None,
    source: str | None = None,
    license_: str | None = None,
    tonemap: str | None = None,
    provenance: str | None = None,
) -> dict[str, Any]:
    plate = np.asarray(Image.open(plate_path).convert("RGB"))
    plate_h, plate_w = plate.shape[:2]
    plate_wh = (plate_w, plate_h)

    meta: dict[str, Any] = {}
    if extraction_manifest is not None:
        meta = json.loads(extraction_manifest.read_text(encoding="utf-8"))

    resolved_provenance = provenance or meta.get("plate_provenance")
    resolved_source = source or meta.get("source")
    resolved_license = license_ or meta.get("license")
    resolved_tonemap = tonemap or meta.get("tonemap")

    missing = [
        name
        for name, value in (
            ("plate_provenance", resolved_provenance),
            ("source", resolved_source),
            ("license", resolved_license),
            ("tonemap", resolved_tonemap),
        )
        if not (isinstance(value, str) and value.strip())
    ]
    if missing:
        raise ValueError(
            "cannot stamp fixture; missing required metadata "
            f"{missing} (supply via extraction manifest or explicit flags)"
        )

    cg_is_placeholder = cg_path is None
    cg = procedural_cg_insert(plate_wh) if cg_is_placeholder else _load_cg(cg_path, plate_wh)
    matte = cg[..., 3]
    if int(matte.min()) == int(matte.max()):
        raise ValueError("CG alpha matte is degenerate (constant); validator would reject it")

    out_dir.mkdir(parents=True, exist_ok=True)
    plate_out = out_dir / "plate_rgb.png"
    cg_out = out_dir / "cg_rgba.png"
    alpha_out = out_dir / "alpha.png"
    Image.fromarray(plate, mode="RGB").save(plate_out)
    Image.fromarray(cg, mode="RGBA").save(cg_out)
    # alpha.png must be byte-identical to cg_rgba's alpha channel (validator
    # tolerates only a 1/255 delta).
    Image.fromarray(matte, mode="L").save(alpha_out)

    files = {
        "plate_rgb.png": _sha256_prefix(plate_out),
        "cg_rgba.png": _sha256_prefix(cg_out),
        "alpha.png": _sha256_prefix(alpha_out),
    }

    manifest: dict[str, Any] = {
        "fixture_id": fixture_id,
        "plate_provenance": resolved_provenance,
        "source": resolved_source,
        "license": resolved_license,
        "tonemap": resolved_tonemap,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "plate_size_wh": [plate_w, plate_h],
        "cg_insert": "procedural_placeholder_shaded_sphere"
        if cg_is_placeholder
        else f"supplied:{cg_path.name}",
        "cg_insert_is_quality_bearing": not cg_is_placeholder,
        "files": files,
    }
    if extraction_manifest is not None:
        manifest["plate_extraction"] = {
            k: meta.get(k)
            for k in (
                "plate_source_kind",
                "source_url",
                "matched_hdri",
                "matched_hdri_sha256_16",
                "projection",
                "view",
                "plate_rgb_sha256_16",
            )
            if k in meta
        }

    (out_dir / "fixture.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plate", type=Path, required=True, help="plate_rgb.png to build the fixture around")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fixture-id", type=str, required=True)
    p.add_argument("--cg", type=Path, help="full-plate-size RGBA CG render; omitted => procedural placeholder")
    p.add_argument("--extraction-manifest", type=Path, help="plate_extraction.json to carry provenance/metadata")
    p.add_argument("--source", type=str)
    p.add_argument("--license", dest="license_", type=str)
    p.add_argument("--tonemap", type=str)
    p.add_argument("--provenance", type=str, help="override plate_provenance (default: from manifest)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    manifest = assemble(
        args.plate,
        args.out_dir,
        fixture_id=args.fixture_id,
        cg_path=args.cg,
        extraction_manifest=args.extraction_manifest,
        source=args.source,
        license_=args.license_,
        tonemap=args.tonemap,
        provenance=args.provenance,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
