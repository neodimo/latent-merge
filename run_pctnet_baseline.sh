#!/bin/bash
# PCT-Net Execution Packet — Latent Merge Phase 1 Harmonic Baseline
# ==============================================================
# Purpose  : Run PCT-Net harmonization on golden fixture (768x432)
#             to produce first non-stub Phase 1 result on real model output
# Designed : 8 GB / 16 GB / 48 GB+ VRAM tiers
# Author   : Gonzo 🤪
# Date     : 2026-05-29

set -euo pipefail

# ─── CUSTOMISE THESE PER RUN ───────────────────────────────────────────────
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
BACKEND="${BACKEND:-pctnet}"
CONFIG="${CONFIG:-configs/phase1_pctnet.json}"
VENV_DIR="${VENV_DIR:-.venv}"
# Device hint (set to 0 for first GPU, or 'cpu')
DEVICE="${DEVICE:-0}"
# ─────────────────────────────────────────────────────────────────────────────

echo "=== PCT-Net Execution Packet ==="
echo "REPO_ROOT : $REPO_ROOT"
echo "BACKEND   : $BACKEND"
echo "CONFIG    : $CONFIG"
echo "DEVICE    : $DEVICE"
echo "VENV_DIR   : $VENV_DIR"
echo ""

# ─── 1. Set up Python env ───────────────────────────────────────────────────
if [ ! -d "$REPO_ROOT/$VENV_DIR" ]; then
    python3 -m venv "$REPO_ROOT/$VENV_DIR"
fi
. "$REPO_ROOT/$VENV_DIR/bin/activate"

pip install --quiet pip setuptools wheel

# ─── 2. Determine GPU memory budget ─────────────────────────────────────────
# Query nvidia-smi if available; otherwise fall back to env override.
# Typical VRAM budgets:
#   RTX 3080 Ti  / RTX 4070 Ti   → ~12 GB  → target compact-8
#   RTX 4080     / RTX 3090      → ~24 GB  → target mid-16
#   A100 / A6000 / RTX 6000 Ada  → 48+ GB  → target full-48

_detect_vram_mb() {
    if command -v nvidia-smi &>/dev/null; then
        nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits \
            2>/dev/null | head -1 | tr -d ' '
    else
        echo ""
    fi
}

VRAM_MB="${VRAM_MB:-$(_detect_vram_mb)}"
VRAM_GB=$((VRAM_MB >= 1024 ? VRAM_MB / 1024 : 0))

echo "Detected VRAM : ${VRAM_MB:-unknown} MB (~${VRAM_GB:-? GB)"

if [ -z "${VRAM_MB:-}" ] || [ "$VRAM_MB" -lt 4096 ]; then
    echo "WARNING: No GPU detected or < 4 GB VRAM. Falling back to CPU."
    TARGET_TIER="cpu"
    DEVICE_HINT="cpu"
elif [ "$VRAM_MB" -lt 12288 ]; then
    TARGET_TIER="compact-8"
    DEVICE_HINT="${DEVICE}"
    echo "→ Tier: compact-8 (8 GB class)"
elif [ "$VRAM_MB" -lt 28672 ]; then
    TARGET_TIER="mid-16"
    DEVICE_HINT="${DEVICE}"
    echo "→ Tier: mid-16 (16 GB class)"
else
    TARGET_TIER="full-48"
    DEVICE_HINT="${DEVICE}"
    echo "→ Tier: full-48 (48 GB+ class)"
fi

# ─── 3. Install core deps ───────────────────────────────────────────────────
CORE_DEPS="numpy>=1.26 Pillow>=10.0"
echo ""
echo "Installing core deps: $CORE_DEPS"
pip install --quiet $CORE_DEPS

# ─── 4. Install torch + libcom ────────────────────────────────────────────
# Torch CUDA variant guide:
#   cu121 = CUDA 12.1 — RTX 3080 Ti / 4070 Ti / 4090 / A6000 Ada / RTX 5000 Ada
#   cu124 = CUDA 12.4 — RTX 50-series (RTX 5090 etc.)
#
# Override TORCH_INDEX_URL to use a mirror if needed.
# For ROCm/HIP users, replace the whole torch install with your distribution wheel.

TORCH_INDEX="${TORCH_INDEX_URL:-https://download.pytorch.org/whl}"

echo ""
echo "Installing torch..."
if [ "$TARGET_TIER" = "cpu" ]; then
    pip install --quiet torch torchvision \
        --index-url "${TORCH_INDEX}/cpu" \
        --extra-index-url "${TORCH_INDEX}/cpu"
else
    # Default to CUDA 12.1; swap to cu124 for RTX 50-series
    pip install --quiet torch torchvision \
        --index-url "${TORCH_INDEX}/cu121" \
        --extra-index-url "${TORCH_INDEX}/whl/cu121"
fi

echo ""
echo "Installing libcom..."
pip install --quiet libcom || \
    pip install --quiet libcom --no-deps && \
    pip install --quiet 'torch>=2.0' 'torchvision>=0.15' 'einops>=0.7'

# ─── 5. Final env sanity ───────────────────────────────────────────────────
python3 - <<'SANITY_EOF'
import sys, importlib
missing = []
for mod in ["numpy", "PIL", "torch", "libcom"]:
    try:
        importlib.import_module(mod)
    except ImportError:
        missing.append(mod)
if missing:
    print("FATAL: missing modules:", missing)
    sys.exit(1)
print("Env sanity OK")
import torch
print("torch", torch.__version__, "| CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    print("VRAM total:", torch.cuda.get_device_properties(0).total_memory / 1024**3, "GB")
SANITY_EOF

# ─── 6. Run the pipeline ───────────────────────────────────────────────────
OUTPUT_DIR="$REPO_ROOT/runs/phase1_pctnet_${TARGET_TIER}"
mkdir -p "$OUTPUT_DIR"

export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"
export LIBCOM_DEVICE="${DEVICE_HINT}"

echo ""
echo "=== Running pipeline ==="
echo "BACKEND  : $BACKEND"
echo "CONFIG   : $CONFIG"
echo "OUTPUT   : $OUTPUT_DIR"
echo "DEVICE   : $DEVICE_HINT"
echo "PYTHONPATH: $PYTHONPATH"
echo ""

python3 - <<'PYEOF'
import sys, json, datetime as dt, zoneinfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline import run_pipeline, PipelineInputs, load_config

config = load_config(Path("configs/phase1_pctnet.json"))
inputs = PipelineInputs(
    plate_rgb = Path("fixtures/golden_synthetic_001") / "plate_rgb.png",
    cg_rgba  = Path("fixtures/golden_synthetic_001") / "cg_rgba.png",
    alpha    = Path("fixtures/golden_synthetic_001") / "alpha.png",
)
output_dir = Path("runs/phase1_pctnet_8gb")

print("Config:", config.backend)
print("Inputs:", inputs.plate_rgb, "/", inputs.cg_rgba, "/", inputs.alpha)
print("Output:", output_dir)
print("Started:", dt.datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")))

job_path = run_pipeline(inputs, output_dir, config)
print("Done. job.json ->", job_path)

with open(job_path) as f:
    job = json.load(f)
print("Backend report:", job.get("backend_report"))
print("Schema:", job.get("schema"))
PYEOF

echo ""
echo "=== Run complete ==="
echo "Check $OUTPUT_DIR/job.json"
