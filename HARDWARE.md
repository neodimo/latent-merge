# Hardware Notes

## Current Machine

- Host: GMKtec NucBox_EVO-X2 / Bazzite
- CPU: AMD Ryzen AI Max+ 395, 32 threads
- RAM: 91 GiB
- GPU: AMD Radeon 8060S / Strix Halo iGPU (built-in)
- USB4: present

## RTX 3080 Ti — eGPU over USB4

- Card: NVIDIA RTX 3080 Ti (laptop/desktop variant)
- Connection: USB4 external GPU (eGPU)
- VRAM: 12 GB (advertised as 16 GB class, actual ~12 GB on this model)
- Driver: `595.58.03`, CUDA 13.2
- Status: **LIVE** — visible as `cuda:0`, `nvidia-smi` works

GPU memory tiers used by `run_pctnet_baseline.sh`:

| Tier | VRAM | GPUs | Status |
|------|------|------|--------|
| `compact-8` | 8–15 GB | RTX 3080 Ti, RTX 4070 | **Test bench** |
| `mid-16` | 16–31 GB | RTX 4080, RTX 3090 | Supported path |
| `full-48` | 48+ GB | A100, A6000 Ada | Future path |

For Phase 1 PCT-Net, the RTX 3080 Ti test bench is sufficient to validate and ship.