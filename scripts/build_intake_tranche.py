#!/usr/bin/env python3
"""Build photographic intake fixtures #2-#5 via the proven matched-HDRI chain.

Ruling this encodes (Gonzo, 2026-08-13, issue #3 YES-with-caveat): a gnomonic
crop of a CC0 equirectangular photo-panorama IS a real photographic plate under
LOCKED L1 -- the plate pixels are untouched camera pixels, and the matched HDRI
is by construction the exact capture that lit them. The real weakness of a
panorama is not provenance but capture geometry: a fixed nodal point yields no
perspective falloff, no DOF and no motion blur, which makes it an *easier*
Layer-2 test than production footage. So the plate carries a `capture_class`
of `panorama_crop`, and the Layer-2 gate additionally requires >= 2
`camera_original` cases before a backend may be called passed.

Selection rationale (the ground-truth call): the four cases below are chosen to
span the lighting regimes that break harmonization differently -- harsh direct
sun with hard shadows, low warm sun with a strong colour cast, indoor soft
ambient, and overcast urban shade. A tranche of four sunny outdoor plates would
be one test run four times.

    .venv/bin/python scripts/build_intake_tranche.py --out-root fixtures
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "bin" / "python"
BLENDER = "blender"

PH = "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/{slug}_4k.hdr"

# slug, fixture id, yaw, pitch, hfov, lighting regime being probed
CASES = [
    ("syferfontein_18d_clear", "pano_syferfontein_harsh_sun", 30.0, -6.0, 72.0,
     "harsh direct midday sun, hard-edged shadows, high dynamic range"),
    ("venice_sunset", "pano_venice_low_sun", 200.0, -4.0, 70.0,
     "low warm sun, strong global colour cast, long shadows"),
    ("st_fagans_interior", "pano_stfagans_indoor_soft", 90.0, -8.0, 75.0,
     "indoor soft ambient, low contrast, mixed colour temperature"),
    ("urban_alley_01", "pano_urban_alley_overcast", 0.0, -6.0, 72.0,
     "overcast urban shade, ambient-dominant, minimal direct key"),
]


def sh(cmd: list[str], **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


VIEW_TRANSFORM = "AgX"
TONEMAP = f"blender-ocio({VIEW_TRANSFORM},look=None,exposure=0.0,gamma=1.0)"


def tonemap_hdr(hdr_path: Path, out_png: Path) -> Path:
    """HDR equirect -> LDR equirect PNG (the plate's photographic pixels).

    The 2026-06-27 chain did this by hand, which is why `pano_to_plate.py`
    accepts an LDR image it never produced. Scripting it makes the tranche
    reproducible and makes the tonemap operator an auditable fixture field
    rather than an undocumented one-off.

    The operator is now Blender's own view transform rather than OpenCV's
    Reinhard, so the plate leaves the pipeline through the identical curve the
    CG render does. Reinhard produced the washed-out, low-contrast plates that
    read as non-photographic (p1..p99 of 43..193 against AgX's 14..233) and,
    worse, guaranteed a tone mismatch no relight stage could ever close.
    """
    if out_png.is_file():
        return out_png
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sh([BLENDER, "-b", "-P", str(ROOT / "scripts" / "tonemap_pano.py"), "--",
        "--hdr", str(hdr_path), "--out", str(out_png),
        "--view-transform", VIEW_TRANSFORM,
        "--meta", str(out_png.with_suffix(".tonemap.json"))])
    return out_png


def fetch_hdr(slug: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        print(f"= cached {dest.name}", flush=True)
        return dest
    url = PH.format(slug=slug)
    print(f"↓ {url}", flush=True)
    urllib.request.urlretrieve(url, dest)
    return dest


def build_case(slug, fid, yaw, pitch, hfov, regime, out_root: Path, work: Path) -> dict:
    hdr = fetch_hdr(slug, work / f"{slug}_4k.hdr")
    pano_ldr = tonemap_hdr(hdr, work / f"{slug}_4k_ldr.png")
    plate_dir = work / fid / "plate"
    cg_dir = work / fid / "cg"

    sh([str(VENV_PY), str(ROOT / "scripts" / "pano_to_plate.py"),
        "--pano", str(pano_ldr), "--out-dir", str(plate_dir),
        "--yaw", str(yaw), "--pitch", str(pitch), "--hfov", str(hfov),
        "--source", f"Poly Haven {slug}", "--license", "CC0",
        "--url", f"https://polyhaven.com/a/{slug}"])

    sh([BLENDER, "-b", "-P", str(ROOT / "scripts" / "render_cg_insert.py"), "--",
        "--hdr", str(hdr),
        "--plate", str(plate_dir / "plate_rgb.png"),
        "--extraction-manifest", str(plate_dir / "plate_extraction.json"),
        "--out-dir", str(cg_dir),
        "--view-transform", VIEW_TRANSFORM, "--verify-ground"])

    sh([str(VENV_PY), str(ROOT / "scripts" / "assemble_fixture.py"),
        "--plate", str(plate_dir / "plate_rgb.png"),
        "--out-dir", str(out_root / fid), "--fixture-id", fid,
        "--cg", str(cg_dir / "cg_rgba.png"),
        "--extraction-manifest", str(plate_dir / "plate_extraction.json")])

    # stamp the capture-class caveat the ruling depends on
    fj = out_root / fid / "fixture.json"
    meta = json.loads(fj.read_text())
    meta["capture_class"] = "panorama_crop"
    meta["tonemap"] = TONEMAP
    # pano_to_plate sees the tonemapped LDR equirect, so it records that as the
    # matched capture. The relight-bearing asset is the HDR the CG was lit by.
    if isinstance(meta.get("plate_provenance_detail"), dict):
        meta["plate_provenance_detail"]["matched_hdri"] = hdr.name
    meta["matched_hdri_path"] = hdr.name
    meta["lighting_regime"] = regime
    meta["ruling"] = "issue#3 YES-with-caveat (Gonzo 2026-08-13); panorama_crop counts as photographic, but Layer-2 needs >=2 camera_original cases"
    fj.write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", default=str(ROOT / "fixtures"))
    ap.add_argument("--work", default="/tmp/lm_intake")
    ap.add_argument("--only", help="build a single fixture id")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    built = []
    for case in CASES:
        if args.only and case[1] != args.only:
            continue
        try:
            built.append(build_case(*case, out_root=out_root, work=work))
            print(f"✅ {case[1]}", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ {case[1]}: {e}", flush=True)
    print(f"\nbuilt {len(built)} case(s) into {out_root}")
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
