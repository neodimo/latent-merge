from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0


def load_rgba(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.0
    return rgba[..., :3], rgba[..., 3:4]


def load_alpha(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)[..., None] / 255.0


def save_rgb(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(array * 255.0, 0, 255).astype(np.uint8)).save(path)


def save_rgba(path: Path, rgb: np.ndarray, alpha: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba = np.dstack((rgb, alpha))
    Image.fromarray(np.clip(rgba * 255.0, 0, 255).astype(np.uint8)).save(path)


def save_alpha(path: Path, alpha: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(alpha[..., 0] * 255.0, 0, 255).astype(np.uint8)).save(path)
