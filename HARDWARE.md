# Hardware Notes

Initial machine scan: 2026-05-20. Updated after Gonzo's 2026-05-27 handoff and Omid's hardware-tier decision.

## Current Machine

- Host: GMKtec NucBox_EVO-X2 / Bazzite
- CPU: AMD Ryzen AI Max+ 395, 32 threads
- RAM: 91 GiB
- iGPU: Radeon 8060S / Strix Halo
- USB4 present
- NVIDIA GPU: RTX 3080 Ti (12 GB) reachable on `card0` / `cuda:0`
- CUDA runtime works inside `latent-merge/.venv`

The earlier "NVIDIA not visible / `nvidia-smi` not installed" note from 2026-05-20 is superseded. The RTX 3080 Ti path is live and is the current local execution target.

## Hardware Tiers For Builds

Omid's direction is to design the Latent Merge tool around three VRAM tiers, with the same Windows + Linux interface that Bert ships for the local UI:

- 8 GB tier: smallest path, low-res proxies and conservative backends. Used as the lower bound to keep the tool usable on common workstation cards.
- 16 GB tier: baseline. Phase 1 backends should target this comfortably, including PCT-Net at proxy resolution.
- 48 GB+ tier: headroom path for full-res and larger diffusion/relight backends.

The current local RTX 3080 Ti (12 GB) sits between the 8 GB and 16 GB tiers and is treated as a live test bench, not as the design baseline.

## Suitable Now

- Nuke scripting and plugin shell work on the iGPU/CPU side
- Data prep and offline harnesses
- EXR/ACES tests
- CUDA inference of PCT-Net-class harmonizers at proxy resolution on the RTX 3080 Ti
- Low-res 512-1024 px model bakeoff for IC-Light/DiffHarmony-class candidates on the same card

## Headroom Constraints

- FLUX-scale or high-res relight will be slow or memory-constrained on 12 GB. Confirm fit before promoting any FLUX-class backend to default.
- 48 GB+ tier work happens on cloud/larger-card paths (ComfyUI cloud, fal.ai, RunPod, or a future local upgrade).
