from __future__ import annotations

import importlib
import sys
import types
import unittest


class _FakeImage:
    size = (641, 359)


class _FakeImages:
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.removed: list[_FakeImage] = []

    def load(self, path: str) -> _FakeImage:
        self.loaded.append(path)
        return _FakeImage()

    def remove(self, image: _FakeImage) -> None:
        self.removed.append(image)


class RenderCgInsertTest(unittest.TestCase):
    def test_image_size_uses_plate_resolution(self) -> None:
        fake_images = _FakeImages()
        fake_bpy = types.SimpleNamespace(data=types.SimpleNamespace(images=fake_images))
        fake_mathutils = types.SimpleNamespace(Vector=object)
        old_bpy = sys.modules.get("bpy")
        old_mathutils = sys.modules.get("mathutils")
        sys.modules["bpy"] = fake_bpy
        sys.modules["mathutils"] = fake_mathutils
        sys.modules.pop("scripts.render_cg_insert", None)
        try:
            module = importlib.import_module("scripts.render_cg_insert")
            self.assertEqual(module._image_size("/tmp/plate_rgb.png"), (641, 359))
            self.assertEqual(fake_images.loaded, ["/tmp/plate_rgb.png"])
            self.assertEqual(len(fake_images.removed), 1)
        finally:
            sys.modules.pop("scripts.render_cg_insert", None)
            if old_bpy is None:
                sys.modules.pop("bpy", None)
            else:
                sys.modules["bpy"] = old_bpy
            if old_mathutils is None:
                sys.modules.pop("mathutils", None)
            else:
                sys.modules["mathutils"] = old_mathutils


if __name__ == "__main__":
    unittest.main()
