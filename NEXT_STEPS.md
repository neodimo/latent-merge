# Next Steps — Live Board (updated 2026-06-17)

Read `LOCKED.md` first. This board reflects REAL state, not aspiration.

**Status: Bert paused (crons/heartbeats off) 06-17 — Gonzo solo on this project for now.**

## Reality check (2026-06-17)

- Only real-plate case we have: `compositingpro_sh009`. Everything else is synthetic or Blender-mediated.
- IC-Light v2 (the relight lane) has NEVER run: wrong weights (SD1.5 FC, not FLUX ControlNet), no `config.json`, HTTP 400, 0 MiB GPU. All "results" to date are PCT-Net color-match only — no real relight has ever been produced.
- Phase3 "real-plate validation" (06-15/06-16) ran headline cases on Blender plates. Those PASS 5/5 numbers are plumbing on fake data, not quality evidence.

## Current cycle (in order)

1. [Gonzo] Build a small REAL-plate eval set the sh009 way: 5-8 cases, pristine photographic plates (B untouched), CG inserted A-over-B, HDRI matched per plate (not a generic 1k studio), contact-shadow + segmentation holdout where needed. Stamp `plate_provenance: photographic`.
2. [Gonzo] Unblock ONE real relight backend on the 3080 Ti: fix IC-Light v2 weights/contract (correct package + `config.json`) OR stand up IC-Light/FLUX relight via local diffusers. Goal: first actual relight output to compare against PCT-Net. 2026-06-20 night and 2026-06-21 morning/afternoon preflights narrowed this: repo symlinked SD1.5 IC-Light weights are present and channel-compatible (`fbc` 12-channel, `fc` 8-channel), `libcuda`/NVML libraries resolve, but this cron scope cannot access GPU device nodes (`/dev/nvidia*` absent, `/proc/driver/nvidia/version` absent, `torch.cuda.is_available=false`, `nvidia-smi` cannot communicate with driver). Evidence: `reports/ic-light-runtime-check-20260620.json`, `reports/ic-light-runtime-check-20260621-morning.json`, `reports/ic-light-runtime-check-20260621-afternoon.json`; reusable check: `PYTHONPATH=. python3 scripts/check_ic_light_runtime.py --require-cuda`.
3. [Gonzo] On the real-plate set, produce a side-by-side raw A-over-B vs PCT-Net vs relight contact sheet + run Layer-1. Post to channel.
4. [Gonzo] ✅ DONE 2026-06-19 (afternoon). Gate already fails closed on non-photographic plates (commit d66bffb). Stamped the sh009 anchor fixture `plate_provenance: photographic` (commit 2505721) so the gate's fixture-metadata fallback recognizes THE real plate. Verified: on `runs/pctnet_compositingpro_sh009/vit` (a job that does not self-declare provenance) the gate resolves unknown→photographic from fixture.json with the stamp, unknown without it. Note: that legacy PCT-Net run still fails `plate_untouched` (0.204 ≫ 0.012) — correct rejection per L2, PCT-Net repaints the whole composite.
5. [Gonzo] ✅ DONE 2026-06-19. Renamed `fixtures/real_plate_blender` -> `fixtures/smoke_blender_set`; scripts renamed and updated; smoke-only warning added to phase3 report README.

## Needs Omid (one decision)

Plate sourcing: Gonzo sources CC0/free real photographic backplates + matched HDRIs (default, starting on your nod), OR you drop in your own shots/footage for your actual use case. Either way the plate stays a pristine photograph.
