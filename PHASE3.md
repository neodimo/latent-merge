# Phase 3 Release Checkpoint — 2026-06-14

Aggressive-timeline milestone (`AUTOMATION.md`): "Phase 3: 2026-06-14 — usable alpha
surface, likely CLI/service before Nuke polish."

## In plain language

The repo now hands a non-developer two ways to run a real CG-over-plate harmonization:

1. A downloadable Windows or Linux UI executable from the `Build UI executables` GitHub
   Action — drop in CG (RGBA), plate, optional matte, click run, and inspect a contact
   sheet plus debug passes.
2. A scripted CLI (`cli/run_phase1.py`) that reads a JSON config and writes the same
   trusted output family.

The composite is still produced by Nuke's contract math: plate stays untouched, only an
adjusted foreground is composited over the original plate. Every run drops a
`job.json` recording inputs, hashes, backend, runtime, and VRAM, so any frame can be
re-justified after the fact.

## Surface chosen for the alpha gate

Locked in `PHASE2.md`: the packaged UI is the user-facing contract; the CLI remains the
developer surface. Both share `core/pipeline.py` so behavior cannot diverge silently.

## Gate evaluation

| Acceptance item | Status | Evidence |
|---|---|---|
| Chosen surface runs without manual internal edits | ✅ | UI binary built by `.github/workflows/Build UI executables`; PCT-Net default ships in-binary. IC Flux v2 is the only path requiring an external CUDA runtime — that setup is now driven from the UI (managed venv + preflight). |
| Basic validation | ✅ | File-type/alpha checks in `ui/local_app.py`; IC Flux runtime preflight; `nvidia-smi` GPU dropdown; rejection diagnostics in `rejection_checks.json`. |
| Progress / failure states | ✅ | IC Flux setup progress + validation logs in UI; CLI prints input/backend/run dir; `job.json` records failure modes. |
| Inspectable debug outputs | ✅ | Per run: `adjusted_fg.png`, `raw_a_over_b.png`, `final_comp.png`, `delta.png`, `alpha_weighted_delta.png`, `correction_matte.png`, `alpha_used.png`, `contact_sheet.jpg`, `job.json`, `rejection_checks.json`. |
| Workflow integration + rollback docs | ✅ (alpha-grade) | `README.md`, `docs/LOCAL_UI.md`, this file. Rollback = download the prior release artifact; UI writes outputs under `runs/ui_jobs/<job-id>/` next to the executable, so multiple versions coexist cleanly. Nuke wrapper is explicitly deferred. |
| Third-party README run path | ✅ | `README.md` Phase 0 / Phase 1 / Local UI sections each run from a clean checkout with one block of commands. Verified on this checkout: `PYTHONPATH=".deps:." python3 cli/run_phase1.py --config configs/phase1_stub.json` writes the full output family. |

Gate status: **alpha surface met.** Production-grade Nuke integration, EXR/ACEScg
execution, and DiMo's representative input cases remain the v1 work.

## How to run from a clean checkout

### Linux (RTX 3080 Ti) — UI

```bash
git clone <repo> latent-merge && cd latent-merge
python3 -m pip install --target .deps -r requirements.txt
PYTHONPATH=".deps:." python3 ui/local_app.py
# open http://127.0.0.1:7865
```

Or download `latent-merge-ui-linux` from the `Build UI executables` workflow artifact,
make it executable, and launch from a writable folder.

### Windows (RTX 3080 Ti) — UI

```powershell
py -m pip install --target .deps -r requirements.txt
$env:PYTHONPATH=".deps;."
py ui/local_app.py
```

Or download `latent-merge-ui-windows` from the workflow artifact and double-click.

### CLI (developer / scripted)

```bash
PYTHONPATH=".deps:." python3 cli/run_phase1.py --config configs/phase1_pctnet.json \
  --plate fixtures/compositingpro_sh009_minimal/plate_rgb.png \
  --cg    fixtures/compositingpro_sh009_minimal/cg_rgba.png \
  --alpha fixtures/compositingpro_sh009_minimal/alpha.png \
  --output-dir runs/phase3_release_check
```

## Expected inputs and outputs

Inputs:
- CG RGBA PNG (A side)
- Plate PNG/JPG (B side)
- Optional matte PNG/JPG; if omitted, A's embedded alpha is used
- Sequences: drop multiple files; the current runner processes the first sorted frame
  and records the uploaded frame count in `ui_job.json` (full-sequence iteration is v1).

Outputs (per job, under `runs/ui_jobs/<job-id>/` or `--output-dir`):
- `final_comp.png` — trusted A-over-B over untouched plate
- `adjusted_fg.png` — model-adjusted foreground only
- `raw_a_over_b.png` — baseline composite for comparison
- `delta.png`, `alpha_weighted_delta.png` — what the model moved
- `correction_matte.png`, `alpha_used.png` — matte diagnostics
- `contact_sheet.jpg` — single-image review tile
- `job.json` — config, input hashes, backend, runtime, peak VRAM, RSS
- `rejection_checks.json` — validation outcomes

## Hardware notes — RTX 3080 Ti (12 GB)

From `PHASE2_SCORING.md` baselines on `cuda:0`:

- PCT-Net @ `golden_synthetic_001`: 2.35s, 134 MiB reserved VRAM, ~1.55 GB RSS.
- PCT-Net @ `compositingpro_sh009`: 2.78s, 242 MiB reserved VRAM, ~1.97 GB RSS.
- Sequence (6 frames, PCT-Net): mean 0.41s/frame, 120 MiB reserved VRAM.
- IC Flux v2: external runtime; requires torch 2.5.1+cu121 + `transformers<5` (v21 pin).

PCT-Net headroom on a 3080 Ti is large — current bottleneck is not VRAM; it is input
variety and identity/integration weighting.

## Known limitations carried into v1

Pulled from `PHASE2_KNOWN_FAILS.md` plus this gate:

1. PCT-Net moves identity more than any other technique (`fg_delta_mean` 0.555). Strong
   integration, but hero-asset weighting is still an open product call.
2. IC Flux relight pulls away from plate (`mean_err_vs_plate` 0.714) — experimental lane.
3. IC Flux runtime is dependency-fragile; pins live in v20/v21 release notes.
4. **Input-case variety below the 10-case bar.** Two stills + one proxy sequence only.
   Closing this needs DiMo's 20–30 representative cases (`NEXT_STEPS.md`).
5. Synthetic rankings do not transfer to real footage — never pick a production default
   from synthetic-only fixtures.
6. Sequence flicker metric is raw frame-to-frame RMSE, not optical-flow-aligned.
7. EXR / ACEScg input is accepted but execution is blocked with a clear error; OIIO/OCIO
   bridge is v1 work.
8. Nuke gizmo wrapper is intentionally absent; alpha surface ships as standalone UI/CLI.

## Next v1 decisions

- **Identity vs integration weighting** — pick the hero-asset metric stance before any
  technique is declared "default" for production.
- **DiMo case intake** — gate v1 on the 20–30 representative cases; everything else is
  pre-test tuning.
- **EXR / ACEScg bridge** — OpenImageIO + OpenColorIO wrapper around the runner so
  artists can hit the working pipeline with EXR plates without manual conversion.
- **Nuke gizmo wrapper** — thin local-service caller; do not embed the model in Nuke.
- **Optical-flow-aligned flicker metric** — replace raw RMSE evaluator.
- **Sequence-first runner mode** — UI currently processes only the first sorted frame
  of a dropped sequence; promote sequence iteration once flicker metric is honest.

## Rollback

- UI: download the previous release artifact (`latent-merge-ui-<os>` from the prior
  workflow run) and launch from a different folder; `runs/ui_jobs/` is per-launch.
- CLI: `git checkout v0.1.0-phase1-pctnet-v21` (last green tag carrying the locked
  Phase 2 surface).
- No shared state, no migrations, no DB — rollback is "use the older binary".
