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

from core.pipeline import PipelineInputs, load_config, run_pipeline


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
    required_paths: tuple[str, ...]
    ignore_patterns: tuple[str, ...] = ("*.msgpack", "flax_*", "*/flax_*")


MODEL_PACKAGES = [
    ModelPackage(
        key="ic-light-v2",
        label="IC-Light V2 ControlNet",
        repo_id=os.environ.get("LATENT_MERGE_IC_LIGHT_REPO", "lllyasviel/ic-light"),
        local_dir=Path(os.environ.get("LATENT_MERGE_IC_FLUX_WEIGHTS", str(WEIGHTS_ROOT / "ic-light-v2"))),
        required_paths=("config.json",),
    ),
    ModelPackage(
        key="flux1-dev",
        label="FLUX.1-dev",
        repo_id=os.environ.get("LATENT_MERGE_FLUX_REPO", "black-forest-labs/FLUX.1-dev"),
        local_dir=Path(os.environ.get("LATENT_MERGE_FLUX_WEIGHTS", str(WEIGHTS_ROOT / "flux1-dev"))),
        required_paths=("model_index.json",),
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
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


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
    with urlopen(request, timeout=120) as response, tmp.open("wb") as handle:
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


def _package_status(package: ModelPackage) -> dict:
    missing = [item for item in package.required_paths if not (package.local_dir / item).exists()]
    present = package.local_dir.is_dir() and not missing
    return {
        "key": package.key,
        "label": package.label,
        "repo_id": package.repo_id,
        "local_dir": str(package.local_dir),
        "required_paths": list(package.required_paths),
        "missing": missing,
        "present": present,
        "size_bytes": _path_size(package.local_dir),
    }


def _model_download_state() -> dict:
    with MODEL_DOWNLOAD_LOCK:
        payload = MODEL_DOWNLOAD_STATE.__dict__.copy()
    total = payload.get("total_bytes", 0) or 0
    done = payload.get("downloaded_bytes", 0) or 0
    payload["percent"] = round((done / total) * 100, 1) if total else 0.0
    payload["packages"] = [_package_status(package) for package in MODEL_PACKAGES]
    payload["ready"] = all(item["present"] for item in payload["packages"])
    payload["disk_warning"] = "IC Flux model setup can require 30 GB or more of free disk space."
    payload["release_posture"] = "Internal/testing backend; model files are downloaded from external sources and are not bundled with Latent Merge."
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

    with urlopen(request, timeout=120) as response, tmp.open(mode) as handle:
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
        if final_status["ready"]:
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
    selected_gpu = _form_first(form, "gpu", "cpu")
    backend = _form_first(form, "backend", "pctnet")
    if backend not in {"pctnet", "pctnet_vit_proxy", "ic_flux_v2", "mean_match_stub"}:
        raise ValueError("backend must be pctnet, pctnet_vit_proxy, ic_flux_v2, or mean_match_stub")
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
    if selected_gpu != "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = selected_gpu
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
