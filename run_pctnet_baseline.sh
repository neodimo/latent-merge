#!/bin/bash
# PCT-Net Execution Packet — Latent Merge Phase 1 Harmonic Baseline
# ==============================================================
# Purpose  : Run PCT-Net harmonization on golden fixture (768x432)
#             to produce first non-stub Phase 1 result on real model output
# Designed : 8 GB / 16 GB / 48 GB+ VRAM tiers
# Author   : Gonzo 🤪
# Date     : 2026-05-29 (updated 2026-05-30)

set -euo pipefail

# ─── CUSTOMISE THESE PER RUN ───────────────────────────────────────────────
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BACKEND="${BACKEND:-pctnet}"
CONFIG="${CONFIG:-configs/phase1_pctnet.json}"
VENV_DIR="${VENV_DIR:-.venv}"
DEVICE="${DEVICE:-0}"          # GPU ordinal (0..n-1), or "cpu"
# ─────────────────────────────────────────────────────────────────────────────

echo "=== PCT-Net Execution Packet ==="
echo "REPO_ROOT : $REPO_ROOT"
echo "BACKEND   : $BACKEND"
echo "CONFIG    : $CONFIG"
echo "DEVICE    : $DEVICE"
echo ""

# ─── 1. Python env ───────────────────────────────────────────────────────────
if [ ! -d "$REPO_ROOT/$VENV_DIR" ]; then
    python3 -m venv "$REPO_ROOT/$VENV_DIR"
fi
. "$REPO_ROOT/$VENV_DIR/bin/activate"
pip install --quiet pip setuptools wheel

# ─── 2. Detect GPU + choose tier ───────────────────────────────────────────
# VRAM tiers:
#   RTX 3080 Ti / RTX 4070      → ~12 GB → compact-8
#   RTX 4080 / RTX 3090         → ~24 GB → mid-16
#   A100 / A6000 Ada / RTX 6000 → 48+ GB → full-48

_detect_vram_mb() {
    if command -v nvidia-smi &>/dev/null; then
        nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits \
            2>/dev/null | head -1 | tr -d ' '
    else
        echo ""
    fi
}

VRAM_MB="${VRAM_MB:-$(_detect_vram_mb)}"

if [ -z "${VRAM_MB:-}" ] || [ "$VRAM_MB" -lt 4096 ]; then
    echo "Detected VRAM : <4 GB — CPU mode"
    TARGET_TIER="cpu"
    DEVICE_HINT="cpu"
elif [ "$VRAM_MB" -lt 14336 ]; then
    echo "Detected VRAM : ${VRAM_MB} MB → compact-8 (~8 GB tier)"
    TARGET_TIER="compact-8"
    DEVICE_HINT="${DEVICE}"
else
    echo "Detected VRAM : ${VRAM_MB} MB → mid-16 or full-48"
    TARGET_TIER="mid-16"
    DEVICE_HINT="${DEVICE}"
fi

# ─── 3. Core deps ────────────────────────────────────────────────────────────
pip install --quiet numpy Pillow

# ─── 4. Torch + dependencies ───────────────────────────────────────────────
TORCH_INDEX="${TORCH_INDEX_URL:-https://download.pytorch.org/whl}"

echo ""
if [ "$TARGET_TIER" = "cpu" ]; then
    echo "Installing torch CPU..."
    pip install --quiet torch torchvision \
        --index-url "${TORCH_INDEX}/cpu" --extra-index-url "${TORCH_INDEX}/cpu"
else
    echo "Installing torch CUDA 12.1..."
    pip install --quiet torch torchvision \
        --index-url "${TORCH_INDEX}/cu121" \
        --extra-index-url "${TORCH_INDEX}/whl/cu121"
fi

pip install --quiet opencv-python-headless kornia tensorboard

# ─── 5. PCT-Net models (download once, reuse) ──────────────────────────────
PCTNET_DIR="$REPO_ROOT/models/pctnet"
if [ ! -f "$PCTNET_DIR/PCTNet_CNN.pth" ]; then
    echo ""
    echo "Downloading PCTNet_CNN.pth pretrained weights..."
    mkdir -p "$PCTNET_DIR"
    # Clone rakutentech repo for model code + weights
    if [ ! -d "/tmp/pctnet_repo" ]; then
        git clone --depth=1 https://github.com/rakutentech/PCT-Net-Image-Harmonization.git /tmp/pctnet_repo
    fi
    cp /tmp/pctnet_repo/pretrained_models/PCTNet_CNN.pth "$PCTNET_DIR/"
    mkdir -p "$PCTNET_DIR/iharm"
    cp -r /tmp/pctnet_repo/iharm/inference  "$PCTNET_DIR/iharm/"
    cp -r /tmp/pctnet_repo/iharm/mconfigs    "$PCTNET_DIR/iharm/"
    cp -r /tmp/pctnet_repo/iharm/model      "$PCTNET_DIR/iharm/"
    cp -r /tmp/pctnet_repo/iharm/utils      "$PCTNET_DIR/iharm/"
fi

# ─── 6. Env sanity ──────────────────────────────────────────────────────────
python3 - <<'EOF'
import sys, importlib
for mod in ["numpy","PIL","torch","cv2","kornia"]:
    try:
        importlib.import_module(mod)
    except ImportError as e:
        print("FATAL: missing", mod, e)
        sys.exit(1)
print("Env sanity OK")
import torch
print("torch", torch.__version__, "| CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
EOF

# ─── 7. Run pipeline ────────────────────────────────────────────────────────
OUTPUT_DIR="$REPO_ROOT/runs/phase1_pctnet_${TARGET_TIER}"
mkdir -p "$OUTPUT_DIR"
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
export CUDA_VISIBLE_DEVICES="${DEVICE_HINT}"

echo ""
echo "=== Running pipeline ==="
echo "BACKEND  : $BACKEND"
echo "CONFIG   : $CONFIG"
echo "OUTPUT   : $OUTPUT_DIR"
echo "GPU      : $DEVICE_HINT"
echo ""

python3 - <<'PYEOF'
import sys, json, datetime as dt, zoneinfo
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.pipeline import run_pipeline, PipelineInputs, load_config

config    = load_config(Path("configs/phase1_pctnet.json"))
inputs    = PipelineInputs(
    plate_rgb = Path("fixtures/golden_synthetic_001") / "plate_rgb.png",
    cg_rgba  = Path("fixtures/golden_synthetic_001") / "cg_rgba.png",
    alpha    = Path("fixtures/golden_synthetic_001") / "alpha.png",
)
output_dir = Path("runs/phase1_pctnet_8gb")

print("Config :", config.backend)
print("Inputs :", inputs.plate_rgb, "/", inputs.cg_rgba, "/", inputs.alpha)
print("Output :", output_dir)
print("Started:", dt.datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")))

job_path = run_pipeline(inputs, output_dir, config)
print("Done. job.json ->", job_path)

with open(job_path) as f:
    job = json.load(f)
print("Backend report:", job.get("backend_report"))
print("Schema       :", job.get("schema"))
PYEOF

echo ""
echo "=== Run complete — check $OUTPUT_DIR/job.json ==="
