#!/usr/bin/env python3
"""Extract a rectilinear photographic plate from an equirectangular panorama.

Why this exists (LOCKED L1): a fixture's plate must be real photography AND the
HDRI must be matched per plate. A CC0 equirectangular HDRI panorama (e.g. Poly
Haven) is itself a real photograph stitched to a full sphere. A rectilinear
(gnomonic) crop of it is therefore a real photographic plate whose matched HDRI
is, by construction, the EXACT capture that lit the scene -- same time, same
place, same sun. This tool produces that crop plus the bookkeeping that ties the
plate to its source panorama so the match is provable, not asserted.

It does NOT write a counted fixture. It emits a plate + an extraction manifest;
fixture assembly (CG insert + alpha + validator metadata) is a separate, gated
step that only runs once DiMo approves the method.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def _sha256_prefix(path: Path, length: int = 16) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def equirect_to_rectilinear(
    pano: np.ndarray,
    out_wh: tuple[int, int],
    yaw_deg: float,
    pitch_deg: float,
    hfov_deg: float,
) -> np.ndarray:
    """Gnomonic projection of an equirectangular panorama into a pinhole view.

    pano: HxWx3 (or HxWxC) array, equirectangular (lon in [-pi, pi], lat in
    [-pi/2, pi/2]). Returns an out_h x out_w x C float array, bilinearly sampled.
    """
    out_w, out_h = out_wh
    ph, pw = pano.shape[:2]
    channels = pano.shape[2] if pano.ndim == 3 else 1
    pano_f = pano.astype(np.float64).reshape(ph, pw, channels)

    hfov = np.radians(hfov_deg)
    # Pinhole focal length in pixel units from horizontal FOV.
    f = (out_w / 2.0) / np.tan(hfov / 2.0)

    xs = np.arange(out_w) - (out_w - 1) / 2.0
    ys = np.arange(out_h) - (out_h - 1) / 2.0
    grid_x, grid_y = np.meshgrid(xs, ys)

    # Camera-space ray directions (z forward, x right, y up).
    dx = grid_x
    dy = -grid_y
    dz = np.full_like(grid_x, f)
    norm = np.sqrt(dx * dx + dy * dy + dz * dz)
    dx, dy, dz = dx / norm, dy / norm, dz / norm

    yaw = np.radians(yaw_deg)
    pitch = np.radians(pitch_deg)

    # Rotate about X (pitch) then Y (yaw).
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)

    # Pitch (about x-axis).
    ry = cp * dy - sp * dz
    rz = sp * dy + cp * dz
    rx = dx
    # Yaw (about y-axis).
    wx = cy * rx + sy * rz
    wy = ry
    wz = -sy * rx + cy * rz

    lon = np.arctan2(wx, wz)
    lat = np.arcsin(np.clip(wy, -1.0, 1.0))

    u = (lon / (2.0 * np.pi) + 0.5) * pw - 0.5
    v = (0.5 - lat / np.pi) * ph - 0.5

    # Bilinear sample with horizontal wrap and vertical clamp.
    u0 = np.floor(u).astype(np.int64)
    v0 = np.floor(v).astype(np.int64)
    fu = (u - u0)[..., None]
    fv = (v - v0)[..., None]
    u0m = u0 % pw
    u1m = (u0 + 1) % pw
    v0c = np.clip(v0, 0, ph - 1)
    v1c = np.clip(v0 + 1, 0, ph - 1)

    c00 = pano_f[v0c, u0m]
    c10 = pano_f[v0c, u1m]
    c01 = pano_f[v1c, u0m]
    c11 = pano_f[v1c, u1m]
    top = c00 * (1 - fu) + c10 * fu
    bot = c01 * (1 - fu) + c11 * fu
    out = top * (1 - fv) + bot * fv
    return out.reshape(out_h, out_w, channels)


def extract(
    pano_path: Path,
    out_dir: Path,
    out_wh: tuple[int, int],
    yaw_deg: float,
    pitch_deg: float,
    hfov_deg: float,
    pano_source: str,
    pano_license: str,
    pano_url: str,
) -> dict[str, Any]:
    pano_img = Image.open(pano_path).convert("RGB")
    pano = np.asarray(pano_img)
    view = equirect_to_rectilinear(pano, out_wh, yaw_deg, pitch_deg, hfov_deg)
    view_u8 = np.clip(np.rint(view), 0, 255).astype(np.uint8)

    out_dir.mkdir(parents=True, exist_ok=True)
    plate_path = out_dir / "plate_rgb.png"
    Image.fromarray(view_u8, mode="RGB").save(plate_path)

    manifest = {
        "plate_provenance": "photographic",
        "plate_source_kind": "equirectangular_panorama_crop",
        "source": pano_source,
        "license": pano_license,
        "source_url": pano_url,
        # The matched HDRI is the panorama itself -- same capture, same light.
        "matched_hdri": pano_path.name,
        "matched_hdri_sha256_16": _sha256_prefix(pano_path),
        "projection": "gnomonic_rectilinear",
        "view": {
            "yaw_deg": yaw_deg,
            "pitch_deg": pitch_deg,
            "hfov_deg": hfov_deg,
            "size_wh": [out_wh[0], out_wh[1]],
        },
        "plate_size_wh": [out_wh[0], out_wh[1]],
        "tonemap": "panorama LDR/tonemapped as provided; HDRI used for relight",
        "plate_rgb_sha256_16": _sha256_prefix(plate_path),
    }
    manifest_path = out_dir / "plate_extraction.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pano", type=Path, required=True, help="equirectangular panorama image")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--yaw", type=float, default=0.0)
    p.add_argument("--pitch", type=float, default=0.0)
    p.add_argument("--hfov", type=float, default=70.0)
    p.add_argument("--source", type=str, default="")
    p.add_argument("--license", type=str, default="")
    p.add_argument("--url", type=str, default="")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    manifest = extract(
        args.pano,
        args.out_dir,
        (args.width, args.height),
        args.yaw,
        args.pitch,
        args.hfov,
        args.source,
        args.license,
        args.url,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
