#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

if getattr(sys, "frozen", False):
    ROOT = Path(getattr(sys, "_MEIPASS")).resolve()
    WORK_ROOT = Path.cwd().resolve()
else:
    ROOT = Path(__file__).resolve().parents[1]
    WORK_ROOT = ROOT

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pipeline import PipelineInputs, load_config, run_pipeline


APP_DIR = Path(__file__).resolve().parent
RUN_ROOT = WORK_ROOT / "runs" / "ui_jobs"
DEFAULT_CONFIG = ROOT / "configs" / "phase1_stub.json"
SUPPORTED_A = {".png", ".exr"}
SUPPORTED_B = {".png", ".jpg", ".jpeg", ".exr"}
IMAGE_OUTPUTS = [
    ("final_comp", "Final Comp"),
    ("adjusted_fg", "Adjusted FG"),
    ("alpha_used", "Alpha"),
    ("delta", "Delta"),
    ("alpha_weighted_delta", "Alpha Weighted Delta"),
]

BACKENDS = [
    {
        "id": "mean_match_stub",
        "name": "Mean Match",
        "tagline": "Conservative scaffold baseline",
        "description": "Matches the foreground's average RGB to the plate under the matte. Small, stable shifts.",
        "parameters": [],
    },
    {
        "id": "pctnet_vit_proxy",
        "name": "PCT-Net ViT",
        "tagline": "Stronger experimental harmonization",
        "description": (
            "A local controllable proxy for the ViT lane while the external PCT-Net checkpoint runner is stabilized. "
            "Higher settings make the change easier to see but can risk CG identity."
        ),
        "parameters": [
            {
                "key": "strength",
                "label": "Transform Strength",
                "min": 0.0,
                "max": 2.0,
                "step": 0.05,
                "default": 1.0,
                "low": "Lower keeps the original CG closer.",
                "high": "Higher pushes harder toward the plate lighting and color.",
            },
            {
                "key": "locality",
                "label": "Scene Locality",
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "default": 0.45,
                "low": "Lower uses broad whole-image statistics.",
                "high": "Higher reacts more to nearby plate context.",
            },
            {
                "key": "contrast",
                "label": "Contrast Match",
                "min": 0.0,
                "max": 1.5,
                "step": 0.05,
                "default": 0.65,
                "low": "Lower preserves the CG's original contrast.",
                "high": "Higher matches the plate's contrast more aggressively.",
            },
            {
                "key": "warmth",
                "label": "Warmth Bias",
                "min": -1.0,
                "max": 1.0,
                "step": 0.05,
                "default": 0.0,
                "low": "Negative cools the foreground.",
                "high": "Positive warms the foreground.",
            },
            {
                "key": "saturation",
                "label": "Saturation",
                "min": 0.0,
                "max": 2.0,
                "step": 0.05,
                "default": 1.0,
                "low": "Lower desaturates the adjusted CG.",
                "high": "Higher increases color intensity.",
            },
            {
                "key": "identity_lock",
                "label": "Identity Lock",
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "default": 0.35,
                "low": "Lower allows larger appearance changes.",
                "high": "Higher preserves the original CG more strongly.",
            },
            {
                "key": "delta_display_gain",
                "label": "Delta Visibility",
                "min": 1.0,
                "max": 8.0,
                "step": 0.25,
                "default": 3.0,
                "low": "Lower shows the raw subtle delta.",
                "high": "Higher amplifies the delta preview only.",
            },
        ],
    },
]


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


def _backend_spec(backend_id: str) -> dict:
    return next((backend for backend in BACKENDS if backend["id"] == backend_id), BACKENDS[0])


def _parse_backend_config(form: ParsedForm) -> dict[str, object]:
    backend_id = _form_first(form, "backend", "mean_match_stub")
    spec = _backend_spec(backend_id)
    parameters: dict[str, float] = {}
    for param in spec["parameters"]:
        raw = _form_first(form, f"param_{param['key']}", str(param["default"]))
        try:
            value = float(raw)
        except ValueError:
            value = float(param["default"])
        parameters[param["key"]] = max(float(param["min"]), min(float(param["max"]), value))
    return {
        "backend": spec["id"],
        "notes": spec["description"],
        "parameters": parameters,
    }


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
    sheet = Image.new("RGB", (width, row_h * 3), (18, 20, 24))
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
    previous_cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if selected_gpu != "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = selected_gpu
    try:
        job_path = run_pipeline(
            PipelineInputs(plate_rgb=plate.first_frame, cg_rgba=cg.first_frame, alpha=alpha_path),
            output_dir,
            load_config(DEFAULT_CONFIG, _parse_backend_config(form)),
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
        if parsed.path == "/api/backends":
            self._send_json(HTTPStatus.OK, {"backends": BACKENDS})
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
        if urlparse(self.path).path != "/api/run":
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
