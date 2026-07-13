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
- Driver observed during 2026-06-07 Phase 2 CUDA sweep: `610.43.02`
- Reset status: **not visible to the current cron worker environment**.
  Between 2026-06-20 and 2026-06-23, repeated runtime checks found no
  `/dev/nvidia*`, no NVIDIA PCI device, `torch.cuda.is_available=false`, and
  `nvidia-smi` unable to communicate with a driver. See
  `reports/ic-light-runtime-check-20260620.json` through
  `reports/ic-light-runtime-check-20260623-morning.json`.
- Treat the 2026-06-07 CUDA sweep as historical. Do not schedule or report
  GPU/IC-Light progress from this worker until a fresh runtime check sees the
  NVIDIA device and a CUDA-capable PyTorch process.

GPU memory tiers used by `run_pctnet_baseline.sh`:

| Tier | VRAM | GPUs | Status |
|------|------|------|--------|
| `compact-8` | 8–15 GB | RTX 3080 Ti, RTX 4070 | **Test bench** |
| `mid-16` | 16–31 GB | RTX 4080, RTX 3090 | Supported path |
| `full-48` | 48+ GB | A100, A6000 Ada | Future path |

For Phase 1 PCT-Net, the RTX 3080 Ti test bench was sufficient during the
historical CUDA sweep. Current worker pulses should assume CPU-only visibility
unless the runtime preflight proves otherwise.
