import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.pano_to_plate import equirect_to_rectilinear, extract


def _marker_pano(h: int = 256, w: int = 512) -> np.ndarray:
    """Equirectangular pano: blue sky above horizon, green ground below,
    and a red vertical bar centered on lon=0 (image center column)."""
    pano = np.zeros((h, w, 3), dtype=np.uint8)
    pano[: h // 2] = (60, 90, 200)   # sky
    pano[h // 2 :] = (40, 160, 60)   # ground
    bar = w // 2
    pano[:, bar - 1 : bar + 1] = (220, 30, 30)  # lon=0 red marker
    return pano


class PanoToPlateTest(unittest.TestCase):
    def test_forward_view_centers_lon0_marker(self):
        pano = _marker_pano()
        view = equirect_to_rectilinear(pano, (200, 200), yaw_deg=0, pitch_deg=0, hfov_deg=40)
        center_col = view[100, 95:105, :].mean(axis=0)
        # Red marker dominates the center column for a forward, level view.
        self.assertGreater(center_col[0], 150)
        self.assertLess(center_col[2], 120)

    def test_horizon_at_vertical_center_for_level_view(self):
        pano = _marker_pano()
        view = equirect_to_rectilinear(pano, (200, 200), yaw_deg=0, pitch_deg=0, hfov_deg=50)
        # Sky (blue) above center, ground (green) below center.
        top = view[40, :, :].mean(axis=0)
        bottom = view[160, :, :].mean(axis=0)
        self.assertGreater(top[2], top[1])      # blue beats green up top
        self.assertGreater(bottom[1], bottom[2])  # green beats blue below

    def test_yaw_shifts_marker_off_center(self):
        pano = _marker_pano()
        # A 30deg yaw should move the lon=0 marker away from frame center.
        view = equirect_to_rectilinear(pano, (200, 200), yaw_deg=30, pitch_deg=0, hfov_deg=40)
        center_col = view[100, 95:105, :].mean(axis=0)
        self.assertLess(center_col[0], 150)  # marker no longer centered

    def test_extract_writes_plate_and_matched_hdri_manifest(self):
        pano = _marker_pano()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pano_path = tmp_path / "test_pano_4k.png"
            Image.fromarray(pano, mode="RGB").save(pano_path)
            out_dir = tmp_path / "plate_out"
            manifest = extract(
                pano_path,
                out_dir,
                (320, 180),
                yaw_deg=0,
                pitch_deg=0,
                hfov_deg=70,
                pano_source="synthetic test pano",
                pano_license="CC0",
                pano_url="https://example.invalid/test",
            )
            self.assertEqual(manifest["plate_provenance"], "photographic")
            self.assertEqual(manifest["matched_hdri"], "test_pano_4k.png")
            self.assertEqual(manifest["plate_size_wh"], [320, 180])
            self.assertTrue((out_dir / "plate_rgb.png").is_file())
            saved = json.loads((out_dir / "plate_extraction.json").read_text())
            self.assertEqual(saved["matched_hdri_sha256_16"], manifest["matched_hdri_sha256_16"])
            plate = np.asarray(Image.open(out_dir / "plate_rgb.png").convert("RGB"))
            self.assertEqual(plate.shape, (180, 320, 3))


if __name__ == "__main__":
    unittest.main()
