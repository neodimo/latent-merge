from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


def _load_checker():
    path = Path("scripts/check_ic_light_runtime.py")
    spec = importlib.util.spec_from_file_location("check_ic_light_runtime_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ICLightRuntimeCheckTest(unittest.TestCase):
    def test_validates_sd15_weight_channel_counts(self) -> None:
        try:
            import torch
            from safetensors.torch import save_file
        except Exception as error:
            self.skipTest(f"safetensors/torch unavailable: {error}")

        checker = _load_checker()
        with tempfile.TemporaryDirectory() as tmp:
            weights = Path(tmp)
            save_file(
                {"conv_in.weight": torch.zeros((320, 12, 3, 3))},
                weights / "iclight_sd15_fbc.safetensors",
            )
            save_file(
                {"conv_in.weight": torch.zeros((320, 8, 3, 3))},
                weights / "iclight_sd15_fc.safetensors",
            )

            status = checker.build_status(weights, require_cuda=False)

        self.assertTrue(status["weights_ready"])
        self.assertTrue(status["ready"])
        self.assertEqual(status["models"]["fbc"]["conv_in_channels"], 12)
        self.assertEqual(status["models"]["fc"]["conv_in_channels"], 8)

    def test_rejects_mismatched_fbc_channels(self) -> None:
        try:
            import torch
            from safetensors.torch import save_file
        except Exception as error:
            self.skipTest(f"safetensors/torch unavailable: {error}")

        checker = _load_checker()
        with tempfile.TemporaryDirectory() as tmp:
            weights = Path(tmp)
            save_file(
                {"conv_in.weight": torch.zeros((320, 8, 3, 3))},
                weights / "iclight_sd15_fbc.safetensors",
            )
            save_file(
                {"conv_in.weight": torch.zeros((320, 8, 3, 3))},
                weights / "iclight_sd15_fc.safetensors",
            )

            status = checker.build_status(weights, require_cuda=False)

        self.assertFalse(status["weights_ready"])
        self.assertFalse(status["ready"])
        self.assertIn("expected 12 conv-in channels", status["models"]["fbc"]["error"])

    def test_reports_host_cuda_diagnostics(self) -> None:
        checker = _load_checker()
        status = checker.build_status(Path("does-not-exist"), require_cuda=True)

        self.assertIn("host_cuda", status)
        self.assertIn("device_nodes", status["host_cuda"])
        self.assertIn("proc_driver_version_present", status["host_cuda"])
        self.assertIn("libcuda_found", status["host_cuda"])
        self.assertIn("libnvidia_ml_found", status["host_cuda"])
        self.assertIn("diagnosis", status["host_cuda"])


if __name__ == "__main__":
    unittest.main()
