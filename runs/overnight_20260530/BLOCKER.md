# IC Flux GPU Blocker — Discovery Record

**Date:** 2026-05-30  
**Operator:** Gonzo (overnight, VPS execution env)  
**Branch:** gonzo/overnight-technique-sweep

---

## Discovery Commands Run and Output

### 1. nvidia-smi
```
$ nvidia-smi
bash: nvidia-smi: command not found
```

### 2. /dev/nvidia* devices
```
$ ls /dev/nvidia*
ls: cannot access '/dev/nvidia*': No such file or directory
```

### 3. /proc/driver/nvidia
```
$ ls /proc/driver/nvidia
ls: cannot access '/proc/driver/nvidia': No such file or directory
```

### 4. CUDA via system Python
```
$ python3 -c "import torch; print(torch.cuda.is_available())"
ModuleNotFoundError: No module named 'torch'
```

### 5. CUDA via latent-merge venv
```
$ .venv/bin/python -c "import torch; print(torch.cuda.is_available())"
ModuleNotFoundError: No module named 'torch'
```

Venv config (`pyvenv.cfg`):
```
home = /usr/bin
include-system-site-packages = false
version = 3.13.5
executable = /usr/bin/python3.13
```
torch is not installed in the VPS-side venv (requirements.txt only lists numpy + Pillow).

### 6. SSH / OpenClaw node paths to local machine
```
$ cat ~/.ssh/config
cat: /data/.ssh/config: No such file or directory

$ ls ~/.ssh/*.pub
ls: cannot access '/data/.ssh/*.pub': No such file or directory
```
No SSH keys configured. OpenClaw `nodes.status` returned `nodes: []` — no paired nodes.

---

## Root Cause

This agent runs on the VPS (187.124.239.114). The RTX 3080 Ti documented in `HARDWARE.md` is on the **local machine** (GMKtec NucBox_EVO-X2 / Bazzite, `card0 / cuda:0`). There is no network path from this VPS execution environment to that machine.

The HARDWARE.md note "CUDA runtime works inside `latent-merge/.venv`" refers to the **local machine venv**, not the VPS-side clone. Both environments have the repo checked out; only the local machine has GPU hardware and a CUDA-capable torch install.

---

## What Needs to Happen on the RTX Host

See `scripts/run_ic_flux_comparison.sh` — a self-contained script ready to execute on the GPU host.

One-liner to run on Gonzo's machine from the repo root:
```bash
bash scripts/run_ic_flux_comparison.sh
```

Expected runtime: 5–15 min one-time setup (weight download), ~2 min per inference step set.

---

## What Is Already Ready (Can Run Now on GPU Host)

- `scripts/ic_flux_runner.py` — complete runner (pipeline call wired up)
- `scripts/run_ic_flux_comparison.sh` — install + weight download + 3-seed comparison run
- Contact sheet structure in `runs/overnight_20260530/` — identical layout; IC Flux outputs will slot straight into the master comparison sheet
- `scripts/overnight_sweep.py` — already has `--compare-ic-flux` flag to regenerate the master sheet once IC Flux outputs exist
