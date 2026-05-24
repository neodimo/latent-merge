# Hardware Notes

Gonzo checked the current machine on 2026-05-20.

## Current Machine

- Host: GMKtec NucBox_EVO-X2 / Bazzite
- CPU: AMD Ryzen AI Max+ 395, 32 threads
- RAM: 91 GiB
- GPU currently visible: Radeon 8060S / Strix Halo iGPU
- USB4 present
- NVIDIA/CUDA not currently visible; `nvidia-smi` not installed/found

## Suitable Now

- Nuke scripting/plugin shell work
- data prep
- EXR/ACES tests
- CPU/offline harnesses
- possible ROCm experiments if stack cooperates

## With Planned RTX 3080 Ti Over USB4/eGPU

- Low-res 512-1024px model bakeoff should be viable.
- fp16/crops/ComfyUI or Python service should fit many candidate models.
- FLUX-scale or high-res work may be slow/memory constrained, but enough to prove whether the idea has legs.
