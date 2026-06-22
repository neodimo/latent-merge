#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS_DIR = ROOT / "weights" / "ic-light-v2"

EXPECTED_MODELS = {
    "fbc": {
        "filename": "iclight_sd15_fbc.safetensors",
        "conv_in_channels": 12,
        "role": "foreground + background conditioned SD1.5 IC-Light",
    },
    "fc": {
        "filename": "iclight_sd15_fc.safetensors",
        "conv_in_channels": 8,
        "role": "foreground/text conditioned SD1.5 IC-Light diagnostic",
    },
}


def _check_weight(path: Path, expected_channels: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "present": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "conv_in_channels": None,
        "valid": False,
        "error": "",
    }
    if not path.is_file():
        result["error"] = "missing"
        return result

    try:
        from safetensors import safe_open
    except Exception as error:  # pragma: no cover - depends on local runtime
        result["error"] = f"safetensors unavailable: {error}"
        return result

    try:
        with safe_open(path, framework="pt", device="cpu") as handle:
            if "conv_in.weight" not in handle.keys():
                result["error"] = "missing conv_in.weight"
                return result
            conv = handle.get_tensor("conv_in.weight")
            channels = int(conv.shape[1])
            result["conv_in_channels"] = channels
            if channels != expected_channels:
                result["error"] = f"expected {expected_channels} conv-in channels, found {channels}"
                return result
    except Exception as error:
        result["error"] = str(error)
        return result

    result["valid"] = True
    return result


def _check_torch_cuda() -> dict[str, Any]:
    result: dict[str, Any] = {
        "torch_imported": False,
        "cuda_available": False,
        "device_count": 0,
        "gpu": None,
        "error": "",
    }
    try:
        import torch
    except Exception as error:
        result["error"] = f"torch unavailable: {error}"
        return result

    result["torch_imported"] = True
    try:
        result["cuda_available"] = bool(torch.cuda.is_available())
        result["device_count"] = int(torch.cuda.device_count())
        if result["cuda_available"]:
            props = torch.cuda.get_device_properties(0)
            result["gpu"] = {
                "name": torch.cuda.get_device_name(0),
                "memory_mb": round(props.total_memory / (1024**2)),
            }
    except Exception as error:
        result["error"] = str(error)
    return result


def _check_nvidia_smi() -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "output": "", "error": ""}
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except FileNotFoundError:
        result["error"] = "nvidia-smi not found"
        return result
    except Exception as error:
        result["error"] = str(error)
        return result

    result["available"] = proc.returncode == 0
    result["output"] = proc.stdout.strip()
    result["error"] = proc.stderr.strip()
    return result


def _check_pci_gpu_inventory() -> dict[str, Any]:
    result: dict[str, Any] = {
        "lspci_available": False,
        "display_devices": [],
        "nvidia_devices": [],
        "error": "",
    }
    try:
        proc = subprocess.run(
            ["lspci"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except FileNotFoundError:
        result["error"] = "lspci not found"
        return result
    except Exception as error:
        result["error"] = str(error)
        return result

    if proc.returncode != 0:
        result["error"] = proc.stderr.strip()
        return result

    result["lspci_available"] = True
    display_lines = []
    nvidia_lines = []
    for line in proc.stdout.splitlines():
        lower = line.lower()
        if any(kind in lower for kind in ("vga", "3d controller", "display controller")):
            display_lines.append(line)
        if "nvidia" in lower:
            nvidia_lines.append(line)
    result["display_devices"] = display_lines
    result["nvidia_devices"] = nvidia_lines
    return result


def _check_host_cuda() -> dict[str, Any]:
    device_nodes = sorted(str(path) for path in Path("/dev").glob("nvidia*"))
    proc_driver = Path("/proc/driver/nvidia/version")
    result: dict[str, Any] = {
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        "nvidia_visible_devices": os.environ.get("NVIDIA_VISIBLE_DEVICES", ""),
        "nvidia_driver_capabilities": os.environ.get("NVIDIA_DRIVER_CAPABILITIES", ""),
        "device_nodes": device_nodes,
        "proc_driver_version_present": proc_driver.is_file(),
        "proc_driver_version": "",
        "libcuda_found": ctypes.util.find_library("cuda") or "",
        "libnvidia_ml_found": ctypes.util.find_library("nvidia-ml") or "",
        "diagnosis": "",
    }

    if proc_driver.is_file():
        try:
            result["proc_driver_version"] = proc_driver.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except Exception as error:
            result["proc_driver_version"] = f"unreadable: {error}"

    if not device_nodes:
        result["diagnosis"] = "no /dev/nvidia* device nodes visible to this process"
    elif not result["proc_driver_version_present"]:
        result["diagnosis"] = "NVIDIA device nodes visible, but driver version is absent"
    elif not result["libcuda_found"]:
        result["diagnosis"] = "NVIDIA driver visible, but libcuda was not found"

    return result


def build_status(weights_dir: Path, require_cuda: bool = False) -> dict[str, Any]:
    models = {
        name: {
            **cfg,
            **_check_weight(weights_dir / cfg["filename"], cfg["conv_in_channels"]),
        }
        for name, cfg in EXPECTED_MODELS.items()
    }
    cuda = _check_torch_cuda()
    smi = _check_nvidia_smi()
    host_cuda = _check_host_cuda()
    pci_gpu_inventory = _check_pci_gpu_inventory()
    weights_ready = all(model["valid"] for model in models.values())
    cuda_ready = bool(cuda["cuda_available"]) and bool(smi["available"])

    missing_or_invalid = [
        name for name, model in models.items() if not model["valid"]
    ]
    errors: list[str] = []
    if missing_or_invalid:
        errors.append("invalid IC-Light weights: " + ", ".join(missing_or_invalid))
    if require_cuda and not cuda_ready:
        errors.append("CUDA runtime unavailable")

    return {
        "schema": "latent-merge.ic-light-runtime-check.v1",
        "weights_dir": str(weights_dir),
        "models": models,
        "torch_cuda": cuda,
        "nvidia_smi": smi,
        "host_cuda": host_cuda,
        "pci_gpu_inventory": pci_gpu_inventory,
        "weights_ready": weights_ready,
        "cuda_ready": cuda_ready,
        "ready": weights_ready and (cuda_ready or not require_cuda),
        "require_cuda": require_cuda,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preflight SD1.5 IC-Light runner weights and local CUDA visibility."
    )
    parser.add_argument("--weights-dir", type=Path, default=DEFAULT_WEIGHTS_DIR)
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    status = build_status(args.weights_dir.resolve(), require_cuda=args.require_cuda)
    rendered = json.dumps(status, indent=2) + "\n"
    print(rendered, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    return 0 if status["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
