#!/usr/bin/env bash
# run_ic_flux_comparison.sh
#
# Self-contained IC-Light V2 / FLUX comparison script.
# Run this on the RTX 3080 Ti host (Gonzo's local machine) from the repo root.
#
# Prerequisites:
#   - latent-merge/.venv with CUDA torch installed (see step 1 below)
#   - ~20 GB free disk for weights
#   - Internet access for one-time HuggingFace download
#
# Usage:
#   cd /path/to/latent-merge
#   bash scripts/run_ic_flux_comparison.sh
#
# On success, outputs land in:
#   runs/overnight_20260530/ic_flux_s42/     seed 42 (primary)
#   runs/overnight_20260530/ic_flux_s123/    seed 123
#   runs/overnight_20260530/ic_flux_s999/    seed 999
#   runs/overnight_20260530/ic_flux_s42_cfg25/  lower CFG variant
#   runs/overnight_20260530/ic_flux_s42_steps30/ higher steps variant

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

WEIGHTS_IC="$REPO_ROOT/weights/ic-light-v2"
WEIGHTS_FLUX="$REPO_ROOT/weights/flux1-dev"
FIXTURE_PLATE="fixtures/golden_synthetic_001/plate_rgb.png"
FIXTURE_CG="fixtures/golden_synthetic_001/cg_rgba.png"
FIXTURE_ALPHA="fixtures/golden_synthetic_001/alpha.png"
OUT_BASE="runs/overnight_20260530"

echo "=== latent-merge IC Flux comparison run ==="
echo "Repo: $REPO_ROOT"
echo "Python: $PYTHON"

# ------------------------------------------------------------------ #
# Step 1: CUDA torch (skip if already installed)
# ------------------------------------------------------------------ #
if ! "$PYTHON" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
    echo "[1/4] Installing CUDA torch ..."
    "$PIP" install --quiet torch torchvision \
        --index-url https://download.pytorch.org/whl/cu121
    "$PIP" install --quiet diffusers transformers accelerate huggingface_hub
    "$PIP" install --quiet xformers || echo "xformers optional — skipping"
else
    echo "[1/4] torch + CUDA already OK"
    "$PYTHON" -c "import torch; print('  GPU:', torch.cuda.get_device_name(0))"
fi

# ------------------------------------------------------------------ #
# Step 2: Download weights (one-time, skip if present)
# ------------------------------------------------------------------ #
echo "[2/4] Weights check ..."

if [ ! -d "$WEIGHTS_IC" ] || [ -z "$(ls -A "$WEIGHTS_IC" 2>/dev/null)" ]; then
    echo "  Downloading IC-Light V2 weights → $WEIGHTS_IC"
    "$PYTHON" -c "
from huggingface_hub import snapshot_download
snapshot_download('lllyasviel/ic-light', local_dir='$WEIGHTS_IC',
                  ignore_patterns=['*.msgpack','flax_*'])
"
else
    echo "  IC-Light weights present"
fi

if [ ! -d "$WEIGHTS_FLUX" ] || [ -z "$(ls -A "$WEIGHTS_FLUX" 2>/dev/null)" ]; then
    echo "  Downloading FLUX.1-dev weights → $WEIGHTS_FLUX"
    echo "  (This is ~25 GB — may take 15-30 min on a fast connection)"
    "$PYTHON" -c "
from huggingface_hub import snapshot_download
snapshot_download('black-forest-labs/FLUX.1-dev', local_dir='$WEIGHTS_FLUX',
                  ignore_patterns=['*.msgpack','flax_*'])
"
else
    echo "  FLUX.1-dev weights present"
fi

# ------------------------------------------------------------------ #
# Step 3: Run comparison variants
# ------------------------------------------------------------------ #
echo "[3/4] Running IC Flux inference ..."

run_variant() {
    local OUT_DIR="$1"; shift
    echo "  → $OUT_DIR"
    "$PYTHON" scripts/ic_flux_runner.py \
        --plate  "$FIXTURE_PLATE" \
        --cg     "$FIXTURE_CG"    \
        --alpha  "$FIXTURE_ALPHA" \
        --weights-dir      "$WEIGHTS_IC"   \
        --flux-weights-dir "$WEIGHTS_FLUX" \
        --out-dir "$OUT_DIR"               \
        "$@"
}

# Primary seed — matches CPU technique seeds for direct comparison
run_variant "$OUT_BASE/ic_flux_s42"       --seed 42  --steps 20 --cfg 3.5

# Seed sweep — check determinism and variance
run_variant "$OUT_BASE/ic_flux_s123"      --seed 123 --steps 20 --cfg 3.5
run_variant "$OUT_BASE/ic_flux_s999"      --seed 999 --steps 20 --cfg 3.5

# CFG sweep — lower CFG = more plate influence, higher = stronger harmonization
run_variant "$OUT_BASE/ic_flux_s42_cfg25" --seed 42  --steps 20 --cfg 2.5

# Step count variant — more steps = better coherence
run_variant "$OUT_BASE/ic_flux_s42_steps30" --seed 42 --steps 30 --cfg 3.5

# ------------------------------------------------------------------ #
# Step 4: Regenerate master comparison sheet
# ------------------------------------------------------------------ #
echo "[4/4] Regenerating master comparison sheet ..."
"$PYTHON" scripts/overnight_sweep.py \
    --compare-ic-flux "$OUT_BASE/ic_flux_s42" \
    --out-dir "$OUT_BASE" || echo "  (--compare-ic-flux flag not yet wired; regenerate manually)"

echo ""
echo "=== IC Flux comparison complete ==="
echo "Artifacts under: $OUT_BASE/ic_flux_*"
echo "Commit with:  git add runs/overnight_20260530/ic_flux_* && git commit -m 'feat: IC Flux comparison runs'"
