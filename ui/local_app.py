#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import mimetypes
import os
import platform
import shutil
import ssl
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from PIL import Image

# Kornia decorates some color/geometry helpers with TorchScript. In a PyInstaller
# onefile executable, Torch cannot inspect those source files after unpacking,
# so disable JIT before importing the PCT-Net stack.
os.environ.setdefault("PYTORCH_JIT", "0")

if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS")).resolve()
    APP_DIR = ROOT / "ui"
    WORK_ROOT = Path.cwd().resolve()
else:
    ROOT = Path(__file__).resolve().parents[1]
    APP_DIR = Path(__file__).resolve().parent
    WORK_ROOT = ROOT

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pipeline import PipelineInputs, ic_flux_runtime_status, load_config, run_pipeline


RUN_ROOT = WORK_ROOT / "runs" / "ui_jobs"
UPDATE_REPO = "neodimo/latent-merge"
UPDATE_ASSET = "latent-merge-ui"
UPDATE_RELEASES = WORK_ROOT / "releases"
UPDATE_BIN = WORK_ROOT / "bin" / UPDATE_ASSET
UPDATE_VERSION_FILE = WORK_ROOT / "CURRENT_VERSION"
DEFAULT_CONFIG = ROOT / "configs" / "phase1_pctnet.json"
SUPPORTED_A = {".png", ".exr"}
SUPPORTED_B = {".png", ".jpg", ".jpeg", ".exr"}
WEIGHTS_ROOT = WORK_ROOT / "weights"
MODEL_PATH_OVERRIDES_FILE = WORK_ROOT / "model_paths.json"
IC_FLUX_RUNTIME_VERSION = os.environ.get("LATENT_MERGE_IC_FLUX_RUNTIME_VERSION", "cuda121-v1")
IC_FLUX_RUNTIME_ROOT = WORK_ROOT / "runtimes" / "ic-flux" / IC_FLUX_RUNTIME_VERSION
IC_FLUX_RUNTIME_CONFIG_FILE = WORK_ROOT / "ic_flux_runtime.json"
IC_FLUX_RUNTIME_DEPS = [
    "numpy",
    "Pillow",
    "diffusers",
    "transformers",
    "accelerate",
    "huggingface_hub",
    "safetensors",
    "opencv-python",
]
IC_FLUX_TORCH_INDEX_URL = os.environ.get("LATENT_MERGE_TORCH_INDEX_URL", "https://download.pytorch.org/whl/cu121")
IMAGE_OUTPUTS = [
    ("raw_a_over_b", "Raw A-over-B"),
    ("final_comp", "Final Comp"),
    ("adjusted_fg", "Adjusted FG"),
    ("alpha_used", "Alpha"),
    ("correction_matte", "Correction Matte"),
    ("delta", "Delta"),
    ("alpha_weighted_delta", "Alpha Weighted Delta"),
]


@dataclass(frozen=True)
class ModelPackage:
    key: str
    label: str
    repo_id: str
    local_dir: Path
    required_any: tuple[tuple[str, ...], ...]
    ignore_patterns: tuple[str, ...] = ("*.msgpack", "flax_*", "*/flax_*")


MODEL_PACKAGES = [
    ModelPackage(
        key="ic-light-v2",
        label="IC-Light V2 ControlNet",
        repo_id=os.environ.get("LATENT_MERGE_IC_LIGHT_REPO", "lllyasviel/ic-light"),
        local_dir=Path(os.environ.get("LATENT_MERGE_IC_FLUX_WEIGHTS", str(WEIGHTS_ROOT / "ic-light-v2"))),
        required_any=(("config.json", "iclight_sd15_fc.safetensors"),),
    ),
    ModelPackage(
        key="flux1-dev",
        label="FLUX.1-dev",
        repo_id=os.environ.get("LATENT_MERGE_FLUX_REPO", "black-forest-labs/FLUX.1-dev"),
        local_dir=Path(os.environ.get("LATENT_MERGE_FLUX_WEIGHTS", str(WEIGHTS_ROOT / "flux1-dev"))),
        required_any=(("model_index.json",),),
    ),
]


@dataclass
class ModelDownloadState:
    running: bool = False
    status: str = "idle"
    phase: str = ""
    current_file: str = ""
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    downloaded_files: int = 0
    total_files: int = 0
    packages: list[dict] = field(default_factory=list)


MODEL_DOWNLOAD_LOCK = threading.Lock()
MODEL_DOWNLOAD_STATE = ModelDownloadState()
MODEL_DOWNLOAD_THREAD: threading.Thread | None = None


@dataclass
class RuntimeSetupState:
    running: bool = False
    status: str = "idle"
    phase: str = ""
    current_command: str = ""
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    log: list[str] = field(default_factory=list)


RUNTIME_SETUP_LOCK = threading.Lock()
RUNTIME_SETUP_STATE = RuntimeSetupState()
RUNTIME_SETUP_THREAD: threading.Thread | None = None


@dataclass(frozen=True)
class UploadGroup:
    first_frame: Path
    count: int
    filenames: list[str]


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    content: bytes


FormValue = str | UploadedFile
ParsedForm = dict[str, list[FormValue]]


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def _current_version() -> str:
    env_version = os.environ.get("LATENT_MERGE_VERSION", "").strip()
    if env_version:
        return env_version
    if UPDATE_VERSION_FILE.is_file():
        return UPDATE_VERSION_FILE.read_text(encoding="utf-8").strip()
    return "unknown"


def _github_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "latent-merge-ui"})
    with urlopen(request, timeout=20, context=_ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _latest_release() -> dict:
    release = _github_json(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest")
    asset = next((item for item in release.get("assets", []) if item.get("name") == UPDATE_ASSET), None)
    if not asset:
        raise ValueError(f"latest release has no {UPDATE_ASSET} asset")
    return {
        "tag": release["tag_name"],
        "name": release.get("name") or release["tag_name"],
        "url": asset["browser_download_url"],
        "digest": asset.get("digest", ""),
        "size": asset.get("size", 0),
        "html_url": release.get("html_url", ""),
    }


def _update_status() -> dict:
    latest = _latest_release()
    current = _current_version()
    digest = latest.get("digest", "")
    executable = Path(sys.executable)
    if current == "unknown" and getattr(sys, "frozen", False) and digest.startswith("sha256:") and executable.is_file():
        if _sha256(executable) == digest.split(":", 1)[1]:
            current = latest["tag"]
    installed_path = UPDATE_RELEASES / f"{UPDATE_ASSET}-{latest['tag']}"
    return {
        "platform": platform.system().lower(),
        "supported": platform.system().lower() == "linux",
        "current": current,
        "latest": latest["tag"],
        "latest_name": latest["name"],
        "release_url": latest["html_url"],
        "installed": installed_path.is_file(),
        "update_available": current != latest["tag"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_update() -> dict:
    if platform.system().lower() != "linux":
        raise ValueError("in-app updates are only wired for the Linux release asset right now")

    latest = _latest_release()
    UPDATE_RELEASES.mkdir(parents=True, exist_ok=True)
    UPDATE_BIN.parent.mkdir(parents=True, exist_ok=True)

    target = UPDATE_RELEASES / f"{UPDATE_ASSET}-{latest['tag']}"
    tmp = target.with_name(target.name + ".download")
    request = Request(latest["url"], headers={"User-Agent": "latent-merge-ui"})
    with urlopen(request, timeout=120, context=_ssl_context()) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)

    digest = latest.get("digest", "")
    if digest.startswith("sha256:"):
        expected = digest.split(":", 1)[1]
        actual = _sha256(tmp)
        if actual != expected:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"download checksum mismatch: {actual} != {expected}")

    tmp.chmod(0o755)
    tmp.replace(target)
    UPDATE_BIN.unlink(missing_ok=True)
    UPDATE_BIN.symlink_to(target)
    UPDATE_VERSION_FILE.write_text(latest["tag"] + "\n", encoding="utf-8")
    return {
        "current": latest["tag"],
        "installed_path": str(target),
        "launcher": str(UPDATE_BIN),
        "restart_required": True,
    }


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _weight_roots() -> list[Path]:
    roots = [
        WEIGHTS_ROOT,
        ROOT / "weights",
        Path.cwd() / "weights",
        Path.home() / "projects" / "latent-merge" / "weights",
        Path.home() / ".openclaw" / "workspace" / "weights",
        Path.home() / ".openclaw" / "workspace" / "repos" / "latent-merge" / "weights",
        Path("/var/home/omid/projects/latent-merge/weights"),
        Path("/var/home/omid/.openclaw/workspace/weights"),
        Path("/var/home/omid/.openclaw/workspace/repos/latent-merge/weights"),
        Path("/home/omid/projects/latent-merge/weights"),
        Path("/home/omid/.openclaw/workspace/weights"),
        Path("/home/omid/.openclaw/workspace/repos/latent-merge/weights"),
    ]
    unique = []
    seen = set()
    for root in roots:
        resolved = root.expanduser()
        key = str(resolved)
        if key not in seen:
            unique.append(resolved)
            seen.add(key)
    return unique


def _hf_cache_snapshot_dirs(package: ModelPackage) -> list[Path]:
    repo_cache_name = "models--" + package.repo_id.replace("/", "--")
    roots = [
        Path(os.environ.get("HF_HOME", "")) / "hub" if os.environ.get("HF_HOME") else None,
        Path(os.environ.get("HUGGINGFACE_HUB_CACHE", "")) if os.environ.get("HUGGINGFACE_HUB_CACHE") else None,
        Path.home() / ".cache" / "huggingface" / "hub",
        Path("/var/home/omid/.cache/huggingface/hub"),
        Path("/home/omid/.cache/huggingface/hub"),
    ]
    candidates: list[Path] = []
    for root in roots:
        if root is None:
            continue
        snapshots = root.expanduser() / repo_cache_name / "snapshots"
        if snapshots.is_dir():
            candidates.extend(item for item in snapshots.iterdir() if item.is_dir())
    return candidates


def _model_path_overrides() -> dict[str, str]:
    if not MODEL_PATH_OVERRIDES_FILE.is_file():
        return {}
    try:
        payload = json.loads(MODEL_PATH_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if isinstance(value, str)}


def _save_model_path_overrides(overrides: dict[str, str]) -> None:
    MODEL_PATH_OVERRIDES_FILE.write_text(json.dumps(overrides, indent=2) + "\n", encoding="utf-8")


def _runtime_python_for_venv(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def _default_runtime_python() -> Path:
    return _runtime_python_for_venv(IC_FLUX_RUNTIME_ROOT / "venv")


def _runtime_config() -> dict[str, object]:
    if not IC_FLUX_RUNTIME_CONFIG_FILE.is_file():
        return {}
    try:
        payload = json.loads(IC_FLUX_RUNTIME_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_runtime_config(python_exe: Path, source: str, validation: dict[str, object]) -> None:
    payload = {
        "schema": "latent-merge.ic-flux-runtime.v1",
        "runtime_version": IC_FLUX_RUNTIME_VERSION,
        "python": str(python_exe),
        "source": source,
        "dependency_specs": {
            "torch_index_url": IC_FLUX_TORCH_INDEX_URL,
            "packages": IC_FLUX_RUNTIME_DEPS,
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python_launcher": sys.executable,
        },
        "last_validation": validation,
        "updated_at": time.time(),
    }
    IC_FLUX_RUNTIME_CONFIG_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _configured_runtime_python() -> str:
    env_python = os.environ.get("LATENT_MERGE_IC_FLUX_PYTHON", "").strip() or os.environ.get("LATENT_MERGE_PYTHON", "").strip()
    if env_python:
        return env_python
    payload = _runtime_config()
    configured = str(payload.get("python", "")).strip()
    if configured:
        return configured
    return str(_default_runtime_python())


def _runtime_setup_payload() -> dict:
    with RUNTIME_SETUP_LOCK:
        setup = RUNTIME_SETUP_STATE.__dict__.copy()
        setup["log_tail"] = setup.pop("log", [])[-80:]
    python_exe = _configured_runtime_python()
    status = ic_flux_runtime_status(python_exe)
    config = _runtime_config()
    status.update(
        {
            "runtime_version": IC_FLUX_RUNTIME_VERSION,
            "configured_python": python_exe,
            "managed_python": str(_default_runtime_python()),
            "install_dir": str(IC_FLUX_RUNTIME_ROOT),
            "config_file": str(IC_FLUX_RUNTIME_CONFIG_FILE),
            "setup": setup,
            "config": config,
            "dependency_specs": {
                "torch_index_url": IC_FLUX_TORCH_INDEX_URL,
                "packages": IC_FLUX_RUNTIME_DEPS,
            },
        }
    )
    return status


def _append_runtime_log(line: str) -> None:
    with RUNTIME_SETUP_LOCK:
        RUNTIME_SETUP_STATE.log.append(line)
        RUNTIME_SETUP_STATE.log = RUNTIME_SETUP_STATE.log[-200:]


def _set_runtime_setup_state(**kwargs: object) -> None:
    with RUNTIME_SETUP_LOCK:
        for key, value in kwargs.items():
            setattr(RUNTIME_SETUP_STATE, key, value)


def _run_runtime_command(command: list[str], phase: str, optional: bool = False) -> None:
    display = " ".join(command)
    _set_runtime_setup_state(phase=phase, current_command=display)
    _append_runtime_log(f"$ {display}")
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60 * 45,
        env=os.environ.copy(),
    )
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    if output:
        for line in output.splitlines()[-80:]:
            _append_runtime_log(line)
    if result.returncode != 0:
        message = f"{phase} failed with exit code {result.returncode}"
        if optional:
            _append_runtime_log(f"Optional step skipped: {message}")
            return
        raise RuntimeError(message)


def _bootstrap_python_candidates() -> list[str]:
    candidates: list[str] = []
    env_python = os.environ.get("LATENT_MERGE_BOOTSTRAP_PYTHON", "").strip()
    if env_python:
        candidates.append(env_python)
    if not getattr(sys, "frozen", False):
        candidates.append(sys.executable)
    candidates.extend(item for item in ("python3.12", "python3.11", "python3.10", "python3", "python") if shutil.which(item))
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = shutil.which(candidate) or candidate
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def _resolve_bootstrap_python() -> str:
    for candidate in _bootstrap_python_candidates():
        try:
            result = subprocess.run(
                [candidate, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return candidate
    raise RuntimeError("Python 3.10+ was not found. Install Python 3.10 or newer, then retry IC Flux setup.")


def _setup_runtime_worker(force: bool = False) -> None:
    try:
        _set_runtime_setup_state(
            running=True,
            status="running",
            phase="Starting",
            current_command="",
            error="",
            started_at=time.time(),
            finished_at=None,
            log=[],
        )
        venv = IC_FLUX_RUNTIME_ROOT / "venv"
        python_exe = _runtime_python_for_venv(venv)
        if force and venv.exists():
            _set_runtime_setup_state(phase="Removing old runtime")
            shutil.rmtree(venv)
        if not python_exe.is_file():
            base_python = _resolve_bootstrap_python()
            venv.parent.mkdir(parents=True, exist_ok=True)
            _run_runtime_command([base_python, "-m", "venv", str(venv)], "Creating IC Flux Python environment")

        py = str(python_exe)
        _run_runtime_command([py, "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"], "Updating installer")
        _run_runtime_command(
            [py, "-m", "pip", "install", "torch", "torchvision", "--index-url", IC_FLUX_TORCH_INDEX_URL],
            "Installing CUDA torch",
        )
        _run_runtime_command([py, "-m", "pip", "install", *IC_FLUX_RUNTIME_DEPS], "Installing IC Flux packages")
        _run_runtime_command([py, "-m", "pip", "install", "xformers"], "Installing optional xformers", optional=True)

        _set_runtime_setup_state(phase="Validating IC Flux Python", current_command=py)
        validation = ic_flux_runtime_status(py)
        if not validation["ready"]:
            raise RuntimeError(validation["message"])
        _save_runtime_config(python_exe, "managed", validation)
        _set_runtime_setup_state(status="complete", phase="Ready", current_command="", error="")
        _append_runtime_log("IC Flux Python runtime is ready.")
    except Exception as error:
        _set_runtime_setup_state(status="error", phase="Setup failed", current_command="", error=str(error))
        _append_runtime_log(f"ERROR: {error}")
    finally:
        _set_runtime_setup_state(running=False, finished_at=time.time())


def _start_runtime_setup(force: bool = False) -> dict:
    global RUNTIME_SETUP_THREAD
    should_start = False
    with RUNTIME_SETUP_LOCK:
        if not RUNTIME_SETUP_STATE.running:
            RUNTIME_SETUP_STATE.running = True
            RUNTIME_SETUP_STATE.status = "running"
            RUNTIME_SETUP_STATE.phase = "Queued"
            RUNTIME_SETUP_STATE.current_command = ""
            RUNTIME_SETUP_STATE.error = ""
            should_start = True
    if should_start:
        RUNTIME_SETUP_THREAD = threading.Thread(target=_setup_runtime_worker, kwargs={"force": force}, daemon=True)
        RUNTIME_SETUP_THREAD.start()
    return _runtime_setup_payload()


def _locate_existing_runtime(raw_path: str) -> dict:
    if not raw_path.strip():
        raise ValueError("Enter a Python executable, virtualenv folder, or install folder.")
    base = Path(raw_path.strip()).expanduser()
    candidates = [base]
    if base.is_dir():
        candidates.extend(
            [
                _runtime_python_for_venv(base),
                _runtime_python_for_venv(base / "venv"),
                base / "bin" / "python",
                base / "Scripts" / "python.exe",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            status = ic_flux_runtime_status(str(candidate))
            if status["ready"]:
                _save_runtime_config(candidate, "located", status)
                payload = _runtime_setup_payload()
                payload["located"] = True
                return payload
            payload = _runtime_setup_payload()
            payload["located"] = False
            payload["error"] = status["message"]
            return payload
    raise ValueError(f"Python runtime not found at {base}")


def _candidate_package_dirs(package: ModelPackage) -> list[Path]:
    overrides = _model_path_overrides()
    candidates = []
    if package.key in overrides:
        candidates.append(Path(overrides[package.key]))
    candidates.append(package.local_dir)
    candidates.extend(root / package.key for root in _weight_roots())
    candidates.extend(_hf_cache_snapshot_dirs(package))
    unique = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        key = str(resolved)
        if key not in seen:
            unique.append(resolved)
            seen.add(key)
    return unique


def _missing_required_paths(package: ModelPackage, local_dir: Path) -> list[str]:
    missing = []
    for group in package.required_any:
        if not any((local_dir / item).exists() for item in group):
            missing.append(" or ".join(group))
    return missing


def _package_status(package: ModelPackage) -> dict:
    candidates = _candidate_package_dirs(package)
    selected_dir = candidates[0]
    selected_missing = _missing_required_paths(package, selected_dir)
    present = False
    for candidate in candidates:
        missing = _missing_required_paths(package, candidate)
        if candidate.is_dir() and not missing:
            selected_dir = candidate
            selected_missing = missing
            present = True
            break
    return {
        "key": package.key,
        "label": package.label,
        "repo_id": package.repo_id,
        "local_dir": str(selected_dir),
        "download_dir": str(package.local_dir),
        "required_paths": [" or ".join(group) for group in package.required_any],
        "searched_dirs": [str(candidate) for candidate in candidates],
        "missing": selected_missing,
        "present": present,
        "size_bytes": _path_size(selected_dir),
    }


def _locate_candidate_dirs(package: ModelPackage, raw_path: Path) -> list[Path]:
    base = raw_path.expanduser().resolve()
    candidates = [
        base,
        base / package.key,
        base / "weights" / package.key,
    ]
    if package.key == "ic-light-v2":
        candidates.extend([base / "ic-light", base / "models--lllyasviel--ic-light"])
    elif package.key == "flux1-dev":
        candidates.extend([base / "FLUX.1-dev", base / "models--black-forest-labs--FLUX.1-dev"])

    expanded: list[Path] = []
    for candidate in candidates:
        if (candidate / "snapshots").is_dir():
            expanded.extend(item for item in (candidate / "snapshots").iterdir() if item.is_dir())
        else:
            expanded.append(candidate)
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in expanded:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _locate_existing_models(raw_path: str) -> dict:
    if not raw_path.strip():
        raise ValueError("Enter a folder path that contains the IC-Light and FLUX model files.")
    base = Path(raw_path.strip()).expanduser()
    if not base.exists():
        raise ValueError(f"folder does not exist: {base}")

    overrides = _model_path_overrides()
    found: dict[str, str] = {}
    missing: list[dict[str, object]] = []
    for package in MODEL_PACKAGES:
        selected: Path | None = None
        searched = _locate_candidate_dirs(package, base)
        for candidate in searched:
            if candidate.is_dir() and not _missing_required_paths(package, candidate):
                selected = candidate
                break
        if selected:
            found[package.key] = str(selected)
        else:
            missing.append(
                {
                    "key": package.key,
                    "label": package.label,
                    "required_paths": [" or ".join(group) for group in package.required_any],
                    "searched_dirs": [str(candidate) for candidate in searched],
                }
            )

    if missing:
        return {
            **_model_download_state(),
            "located": False,
            "found": found,
            "missing_at_path": missing,
            "error": "That folder does not contain all required IC Flux model files.",
        }

    overrides.update(found)
    _save_model_path_overrides(overrides)
    _set_model_download_state(status="complete", phase="Ready", error="", current_file="")
    return {**_model_download_state(), "located": True, "found": found}


def _model_download_state() -> dict:
    with MODEL_DOWNLOAD_LOCK:
        payload = MODEL_DOWNLOAD_STATE.__dict__.copy()
    total = payload.get("total_bytes", 0) or 0
    done = payload.get("downloaded_bytes", 0) or 0
    payload["percent"] = round((done / total) * 100, 1) if total else 0.0
    payload["packages"] = [_package_status(package) for package in MODEL_PACKAGES]
    payload["models_ready"] = all(item["present"] for item in payload["packages"])
    payload["runtime"] = _runtime_setup_payload()
    payload["ready"] = bool(payload["models_ready"] and payload["runtime"]["ready"])
    payload["disk_warning"] = "IC Flux model setup can require 30 GB or more of free disk space."
    payload["release_posture"] = (
        "Internal/testing backend; model files and the CUDA Python runtime are external and are not bundled with Latent Merge."
    )
    return payload


def _set_model_download_state(**kwargs: object) -> None:
    with MODEL_DOWNLOAD_LOCK:
        for key, value in kwargs.items():
            setattr(MODEL_DOWNLOAD_STATE, key, value)


def _should_skip_hf_file(filename: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(filename, pattern) for pattern in patterns)


def _hf_file_list(package: ModelPackage) -> list[dict[str, object]]:
    try:
        from huggingface_hub import HfApi
    except ImportError as error:
        raise RuntimeError(
            "huggingface_hub is required for model downloads. Install requirements.txt, then retry."
        ) from error

    api = HfApi()
    info = api.model_info(package.repo_id, files_metadata=True)
    files = []
    for sibling in info.siblings:
        filename = sibling.rfilename
        if _should_skip_hf_file(filename, package.ignore_patterns):
            continue
        files.append({"filename": filename, "size": int(sibling.size or 0)})
    if not files:
        raise RuntimeError(f"{package.repo_id} did not return downloadable files")
    return files


def _download_hf_file(package: ModelPackage, filename: str, size: int) -> None:
    try:
        from huggingface_hub import hf_hub_url
        from huggingface_hub.utils import build_hf_headers
    except ImportError as error:
        raise RuntimeError(
            "huggingface_hub is required for model downloads. Install requirements.txt, then retry."
        ) from error

    target = package.local_dir / filename
    tmp = target.with_name(target.name + ".download")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and (not size or target.stat().st_size == size):
        _set_model_download_state(
            downloaded_bytes=MODEL_DOWNLOAD_STATE.downloaded_bytes + (size or target.stat().st_size),
            downloaded_files=MODEL_DOWNLOAD_STATE.downloaded_files + 1,
        )
        return

    url = hf_hub_url(package.repo_id, filename)
    headers = build_hf_headers(token=None)
    request = Request(url, headers=headers)
    existing = tmp.stat().st_size if tmp.is_file() else 0
    mode = "ab" if existing else "wb"
    if existing:
        request.add_header("Range", f"bytes={existing}-")
        _set_model_download_state(downloaded_bytes=MODEL_DOWNLOAD_STATE.downloaded_bytes + existing)

    with urlopen(request, timeout=120, context=_ssl_context()) as response, tmp.open(mode) as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            _set_model_download_state(downloaded_bytes=MODEL_DOWNLOAD_STATE.downloaded_bytes + len(chunk))

    if size and tmp.stat().st_size != size:
        raise RuntimeError(f"download size mismatch for {filename}")
    tmp.replace(target)
    _set_model_download_state(downloaded_files=MODEL_DOWNLOAD_STATE.downloaded_files + 1)


def _download_models_worker() -> None:
    try:
        _set_model_download_state(
            running=True,
            status="running",
            phase="Checking model manifests",
            current_file="",
            error="",
            started_at=time.time(),
            finished_at=None,
            downloaded_bytes=0,
            total_bytes=0,
            downloaded_files=0,
            total_files=0,
        )
        missing_packages = [package for package in MODEL_PACKAGES if not _package_status(package)["present"]]
        package_files: list[tuple[ModelPackage, list[dict[str, object]]]] = []
        total_bytes = 0
        total_files = 0
        for package in missing_packages:
            _set_model_download_state(phase=f"Reading {package.label} manifest")
            files = _hf_file_list(package)
            package_files.append((package, files))
            total_bytes += sum(int(item["size"] or 0) for item in files)
            total_files += len(files)

        _set_model_download_state(total_bytes=total_bytes, total_files=total_files)
        for package, files in package_files:
            package.local_dir.mkdir(parents=True, exist_ok=True)
            for item in files:
                filename = str(item["filename"])
                _set_model_download_state(phase=f"Downloading {package.label}", current_file=filename)
                _download_hf_file(package, filename, int(item["size"] or 0))

        final_status = _model_download_state()
        if final_status["models_ready"]:
            _set_model_download_state(status="complete", phase="Ready", current_file="")
        else:
            missing = []
            for package in final_status["packages"]:
                for item in package["missing"]:
                    missing.append(f"{package['key']}/{item}")
            raise RuntimeError("download finished but required files are still missing: " + ", ".join(missing))
    except Exception as error:
        _set_model_download_state(
            status="error",
            phase="Download failed",
            current_file="",
            error=str(error),
        )
    finally:
        _set_model_download_state(running=False, finished_at=time.time())


def _start_model_download() -> dict:
    global MODEL_DOWNLOAD_THREAD
    already_running = False
    already_ready = False
    with MODEL_DOWNLOAD_LOCK:
        if MODEL_DOWNLOAD_STATE.running:
            already_running = True
        elif all(_package_status(package)["present"] for package in MODEL_PACKAGES):
            MODEL_DOWNLOAD_STATE.status = "complete"
            MODEL_DOWNLOAD_STATE.phase = "Ready"
            MODEL_DOWNLOAD_STATE.error = ""
            already_ready = True
        else:
            MODEL_DOWNLOAD_THREAD = threading.Thread(target=_download_models_worker, daemon=True)
            MODEL_DOWNLOAD_THREAD.start()
    if already_running or already_ready:
        return _model_download_state()
    return _model_download_state()


def _safe_name(name: str) -> str:
    cleaned = Path(name).name.replace("\\", "_").replace("/", "_").strip()
    return cleaned or f"upload-{uuid.uuid4().hex}"


def _extension(path: Path) -> str:
    return path.suffix.lower()


def _list_gpus() -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return [{"id": "cpu", "label": "CPU / no NVIDIA GPU detected", "memory_mb": ""}]

    gpus = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        index, name, memory = parts[:3]
        gpus.append({"id": index, "label": f"GPU {index}: {name} ({memory} MB)", "memory_mb": memory})
    return gpus or [{"id": "cpu", "label": "CPU / no NVIDIA GPU detected", "memory_mb": ""}]


def _parse_disposition(value: str) -> dict[str, str]:
    parts = [part.strip() for part in value.split(";")]
    parsed: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        parsed[key.strip().lower()] = raw.strip().strip('"')
    return parsed


def _parse_multipart(body: bytes, content_type: str) -> ParsedForm:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("expected multipart form data")
    boundary = content_type.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
    if not boundary:
        raise ValueError("missing multipart boundary")

    form: ParsedForm = {}
    delimiter = b"--" + boundary.encode("utf-8")
    for raw_part in body.split(delimiter):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].rstrip(b"\r\n")
        header_blob, sep, content = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = {}
        for line in header_blob.decode("utf-8", "replace").split("\r\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        disposition = headers.get("content-disposition", "")
        params = _parse_disposition(disposition)
        name = params.get("name")
        if not name:
            continue
        filename = params.get("filename")
        if filename:
            value: FormValue = UploadedFile(filename=filename, content=content)
        else:
            value = content.decode("utf-8", "replace")
        form.setdefault(name, []).append(value)
    return form


def _form_first(form: ParsedForm, field: str, default: str = "") -> str:
    values = form.get(field, [])
    if not values:
        return default
    value = values[0]
    return value if isinstance(value, str) else default


def _form_float(form: ParsedForm, field: str, default: float, minimum: float, maximum: float) -> float:
    raw = _form_first(form, field, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{field} must be a number") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
    return value


def _form_int(form: ParsedForm, field: str, default: int, minimum: int, maximum: int) -> int:
    value = round(_form_float(form, field, float(default), float(minimum), float(maximum)))
    return int(value)


def _save_uploads(form: ParsedForm, field: str, dest: Path, allowed: set[str]) -> UploadGroup:
    files = [item for item in form.get(field, []) if isinstance(item, UploadedFile) and item.filename]
    if not files:
        raise ValueError(f"missing {field} input")

    dest.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for item in files:
        filename = _safe_name(item.filename)
        path = dest / filename
        ext = _extension(path)
        if ext not in allowed:
            raise ValueError(f"{field} file '{filename}' is not supported yet")
        path.write_bytes(item.content)
        saved.append(path)

    saved.sort(key=lambda path: path.name)
    return UploadGroup(first_frame=saved[0], count=len(saved), filenames=[path.name for path in saved])


def _derive_alpha(cg_path: Path, output_path: Path) -> Path:
    if _extension(cg_path) == ".exr":
        raise ValueError("EXR alpha extraction needs the OpenImageIO/OpenColorIO bridge; provide a PNG alpha proxy for now")
    image = Image.open(cg_path).convert("RGBA")
    alpha = image.getchannel("A")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    alpha.save(output_path)
    return output_path


def _validate_runtime_inputs(cg: Path, plate: Path, alpha: Path) -> None:
    exr_inputs = [path.name for path in (cg, plate, alpha) if _extension(path) == ".exr"]
    if exr_inputs:
        raise ValueError(
            "EXR/ACEScg files are accepted in the UI contract but not converted by this scaffold yet. "
            "Use sRGB PNG/JPG proxies for this pass. Blocked files: " + ", ".join(exr_inputs)
        )


def _build_contact_sheet(job_dir: Path, job: dict) -> Path:
    thumbs = []
    for key, label in IMAGE_OUTPUTS:
        path = Path(job["outputs"][key])
        image = Image.open(path).convert("RGB")
        image.thumbnail((360, 240), Image.Resampling.LANCZOS)
        thumbs.append((label, image.copy()))

    width = 720
    row_h = 292
    rows = (len(thumbs) + 1) // 2
    sheet = Image.new("RGB", (width, row_h * rows), (18, 20, 24))
    try:
        from PIL import ImageDraw, ImageFont

        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default()
        for idx, (label, image) in enumerate(thumbs):
            col = idx % 2
            row = idx // 2
            x = col * 360
            y = row * row_h
            draw.text((x + 14, y + 12), label, fill=(225, 229, 235), font=font)
            sheet.paste(image, (x + 14, y + 38))
    except Exception:
        for idx, (_, image) in enumerate(thumbs):
            sheet.paste(image, ((idx % 2) * 360 + 14, (idx // 2) * row_h + 38))

    path = job_dir / "contact_sheet.jpg"
    sheet.save(path, quality=92)
    return path


def _run_ui_job(form: ParsedForm) -> dict:
    selected_gpu = _form_first(form, "gpu", "cpu")
    backend = _form_first(form, "backend", "pctnet")
    if backend not in {"pctnet", "pctnet_vit_proxy", "ic_flux_v2", "mean_match_stub"}:
        raise ValueError("backend must be pctnet, pctnet_vit_proxy, ic_flux_v2, or mean_match_stub")

    ic_flux_package_dirs: dict[str, str] | None = None
    if backend == "ic_flux_v2":
        model_state = _model_download_state()
        if not model_state["models_ready"]:
            raise ValueError("IC Flux models are missing. Use Download IC Flux Models before running this backend.")
        if not model_state["runtime"]["ready"]:
            runtime = model_state["runtime"]
            raise ValueError(
                "IC Flux Python runtime is not ready. "
                f"{runtime['message']} Set LATENT_MERGE_PYTHON to a ready environment, or run: {runtime['install_hint']}"
            )
        ic_flux_package_dirs = {item["key"]: item["local_dir"] for item in model_state["packages"]}

    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    job_dir = RUN_ROOT / job_id
    input_dir = job_dir / "inputs"

    cg = _save_uploads(form, "cg", input_dir / "cg", SUPPORTED_A)
    plate = _save_uploads(form, "plate", input_dir / "plate", SUPPORTED_B)
    if any(isinstance(item, UploadedFile) and item.filename for item in form.get("alpha", [])):
        alpha = _save_uploads(form, "alpha", input_dir / "alpha", SUPPORTED_A | {".jpg", ".jpeg"})
        alpha_path = alpha.first_frame
        alpha_count = alpha.count
    else:
        alpha_path = _derive_alpha(cg.first_frame, input_dir / "derived_alpha.png")
        alpha_count = 1

    _validate_runtime_inputs(cg.first_frame, plate.first_frame, alpha_path)

    output_dir = job_dir / "outputs"
    adjustment_strength = _form_float(form, "adjustment_strength", 1.0, 0.0, 2.5)
    delta_preview_gain = _form_float(form, "delta_preview_gain", 4.0, 1.0, 16.0)
    correction_softness_px = _form_float(form, "correction_softness_px", 0.0, 0.0, 24.0)
    correction_choke_px = _form_int(form, "correction_choke_px", 0, -24, 24)
    vit_context = _form_float(form, "vit_context", 0.45, 0.0, 1.0)
    vit_contrast = _form_float(form, "vit_contrast", 0.65, 0.0, 1.5)
    vit_warmth = _form_float(form, "vit_warmth", 0.0, -1.0, 1.0)
    vit_saturation = _form_float(form, "vit_saturation", 1.0, 0.0, 2.0)
    vit_identity_lock = _form_float(form, "vit_identity_lock", 0.35, 0.0, 1.0)
    ic_flux_seed = _form_int(form, "ic_flux_seed", 42, 0, 2147483647)
    ic_flux_steps = _form_int(form, "ic_flux_steps", 20, 1, 60)
    ic_flux_cfg = _form_float(form, "ic_flux_cfg", 3.5, 1.0, 10.0)
    ic_flux_cond_strength = _form_float(form, "ic_flux_cond_strength", 0.75, 0.0, 1.5)
    ic_flux_resolution = _form_int(form, "ic_flux_resolution", 768, 384, 1536)
    ic_flux_fp16 = _form_first(form, "ic_flux_fp16", "1") != "0"
    config = replace(
        load_config(DEFAULT_CONFIG),
        backend=backend,
        adjustment_strength=adjustment_strength,
        delta_preview_gain=delta_preview_gain,
        correction_softness_px=correction_softness_px,
        correction_choke_px=correction_choke_px,
        vit_context=vit_context,
        vit_contrast=vit_contrast,
        vit_warmth=vit_warmth,
        vit_saturation=vit_saturation,
        vit_identity_lock=vit_identity_lock,
        ic_flux_seed=ic_flux_seed,
        ic_flux_steps=ic_flux_steps,
        ic_flux_cfg=ic_flux_cfg,
        ic_flux_cond_strength=ic_flux_cond_strength,
        ic_flux_resolution=ic_flux_resolution,
        ic_flux_fp16=ic_flux_fp16,
    )
    previous_cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    previous_ic_enabled = os.environ.get("LATENT_MERGE_ENABLE_IC_FLUX")
    previous_ic_python = os.environ.get("LATENT_MERGE_IC_FLUX_PYTHON")
    previous_ic_weights = os.environ.get("LATENT_MERGE_IC_FLUX_WEIGHTS")
    previous_flux_weights = os.environ.get("LATENT_MERGE_FLUX_WEIGHTS")
    if selected_gpu != "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = selected_gpu
    if backend == "ic_flux_v2":
        os.environ["LATENT_MERGE_ENABLE_IC_FLUX"] = "1"
        os.environ["LATENT_MERGE_IC_FLUX_PYTHON"] = model_state["runtime"]["python"]
        os.environ["LATENT_MERGE_IC_FLUX_WEIGHTS"] = ic_flux_package_dirs["ic-light-v2"]
        os.environ["LATENT_MERGE_FLUX_WEIGHTS"] = ic_flux_package_dirs["flux1-dev"]
    try:
        job_path = run_pipeline(
            PipelineInputs(plate_rgb=plate.first_frame, cg_rgba=cg.first_frame, alpha=alpha_path),
            output_dir,
            config,
        )
    finally:
        if previous_cuda_visible is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = previous_cuda_visible
        if previous_ic_enabled is None:
            os.environ.pop("LATENT_MERGE_ENABLE_IC_FLUX", None)
        else:
            os.environ["LATENT_MERGE_ENABLE_IC_FLUX"] = previous_ic_enabled
        if previous_ic_python is None:
            os.environ.pop("LATENT_MERGE_IC_FLUX_PYTHON", None)
        else:
            os.environ["LATENT_MERGE_IC_FLUX_PYTHON"] = previous_ic_python
        if previous_ic_weights is None:
            os.environ.pop("LATENT_MERGE_IC_FLUX_WEIGHTS", None)
        else:
            os.environ["LATENT_MERGE_IC_FLUX_WEIGHTS"] = previous_ic_weights
        if previous_flux_weights is None:
            os.environ.pop("LATENT_MERGE_FLUX_WEIGHTS", None)
        else:
            os.environ["LATENT_MERGE_FLUX_WEIGHTS"] = previous_flux_weights

    job = json.loads(job_path.read_text(encoding="utf-8"))
    contact_sheet = _build_contact_sheet(job_dir, job)
    metadata = {
        "job_id": job_id,
        "gpu": selected_gpu,
        "sequence": {
            "cg_frames_uploaded": cg.count,
            "plate_frames_uploaded": plate.count,
            "alpha_frames_uploaded": alpha_count,
            "active_frame": {
                "cg": cg.first_frame.name,
                "plate": plate.first_frame.name,
                "alpha": alpha_path.name,
            },
        },
        "job_json": f"/file?path={job_path.relative_to(WORK_ROOT)}",
        "contact_sheet": f"/file?path={contact_sheet.relative_to(WORK_ROOT)}",
        "images": [
            {
                "key": key,
                "label": label,
                "url": f"/file?path={Path(job['outputs'][key]).relative_to(WORK_ROOT)}",
            }
            for key, label in IMAGE_OUTPUTS
        ],
        "backend": job["backend_report"]["name"],
        "controls": {
            "adjustment_strength": adjustment_strength,
            "delta_preview_gain": delta_preview_gain,
            "correction_softness_px": correction_softness_px,
            "correction_choke_px": correction_choke_px,
            "vit_context": vit_context,
            "vit_contrast": vit_contrast,
            "vit_warmth": vit_warmth,
            "vit_saturation": vit_saturation,
            "vit_identity_lock": vit_identity_lock,
            "ic_flux_seed": ic_flux_seed,
            "ic_flux_steps": ic_flux_steps,
            "ic_flux_cfg": ic_flux_cfg,
            "ic_flux_cond_strength": ic_flux_cond_strength,
            "ic_flux_resolution": ic_flux_resolution,
            "ic_flux_fp16": ic_flux_fp16,
        },
        "contract": job["contract"],
    }
    (job_dir / "ui_job.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


class Handler(BaseHTTPRequestHandler):
    server_version = "LatentMergeUI/0.1"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: object) -> None:
        self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = (APP_DIR / "index.html").read_bytes()
            self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")
            return
        if parsed.path == "/app.css":
            self._send(HTTPStatus.OK, (APP_DIR / "app.css").read_bytes(), "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._send(HTTPStatus.OK, (APP_DIR / "app.js").read_bytes(), "text/javascript; charset=utf-8")
            return
        if parsed.path == "/icon.png":
            self._send(HTTPStatus.OK, (APP_DIR / "icon.png").read_bytes(), "image/png")
            return
        if parsed.path == "/api/gpus":
            self._send_json(HTTPStatus.OK, {"gpus": _list_gpus()})
            return
        if parsed.path == "/api/update/status":
            try:
                self._send_json(HTTPStatus.OK, _update_status())
            except Exception as error:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
            return
        if parsed.path == "/api/models/ic-flux/status":
            self._send_json(HTTPStatus.OK, _model_download_state())
            return
        if parsed.path == "/api/models/ic-flux/runtime/status":
            self._send_json(HTTPStatus.OK, _runtime_setup_payload())
            return
        if parsed.path == "/file":
            query = parse_qs(parsed.query)
            raw_path = query.get("path", [""])[0]
            requested = (WORK_ROOT / raw_path).resolve()
            if not requested.is_file() or (requested != WORK_ROOT and WORK_ROOT not in requested.parents):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "file not found"})
                return
            content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
            self._send(HTTPStatus.OK, requested.read_bytes(), content_type)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        parsed_path = urlparse(self.path).path
        if parsed_path == "/api/update":
            try:
                self._send_json(HTTPStatus.OK, _download_update())
            except Exception as error:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
            return
        if parsed_path == "/api/models/ic-flux/download":
            self._send_json(HTTPStatus.ACCEPTED, _start_model_download())
            return
        if parsed_path == "/api/models/ic-flux/runtime/setup":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
                self._send_json(HTTPStatus.ACCEPTED, _start_runtime_setup(force=bool(payload.get("force"))))
            except Exception as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if parsed_path == "/api/models/ic-flux/runtime/locate":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._send_json(HTTPStatus.OK, _locate_existing_runtime(str(payload.get("path", ""))))
            except Exception as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if parsed_path == "/api/models/ic-flux/locate":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._send_json(HTTPStatus.OK, _locate_existing_models(str(payload.get("path", ""))))
            except Exception as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if parsed_path != "/api/run":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            form = _parse_multipart(self.rfile.read(length), self.headers.get("Content-Type", ""))
            self._send_json(HTTPStatus.OK, _run_ui_job(form))
        except Exception as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local latent-merge UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7865)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"latent-merge UI: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
