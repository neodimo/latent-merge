from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


def _load_local_app(tmp_path: Path):
    os.environ["LATENT_MERGE_IC_FLUX_WEIGHTS"] = str(tmp_path / "weights" / "ic-light-v2")
    os.environ["LATENT_MERGE_FLUX_WEIGHTS"] = str(tmp_path / "weights" / "flux1-dev")

    spec = importlib.util.spec_from_file_location("latent_merge_local_app_test", Path("ui/local_app.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ICFluxModelStatusTest(unittest.TestCase):
    def test_rejects_sd15_safetensors_without_flux_controlnet_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ic_light = tmp_path / "weights" / "ic-light-v2"
            ic_light.mkdir(parents=True)
            (ic_light / "iclight_sd15_fc.safetensors").write_bytes(b"not-a-real-weight")

            flux = tmp_path / "weights" / "flux1-dev"
            flux.mkdir(parents=True)
            (flux / "model_index.json").write_text("{}\n", encoding="utf-8")

            local_app = _load_local_app(tmp_path)

            package = next(item for item in local_app.MODEL_PACKAGES if item.key == "ic-light-v2")
            status = local_app._package_status(package)

            self.assertFalse(status["present"])
            self.assertEqual(status["missing"], ["config.json"])


if __name__ == "__main__":
    unittest.main()
