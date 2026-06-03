# Latent Merge

Project channel: `#latent-merge` planned.
Origin: Discord `#project-planning`, 2026-05-20.

## Files

- `PROJECT_MEMORY.md` - current project synthesis and decision state
- `SPEC_DRAFT.md` - current aggressive v0 spec, gates, timeline, and risk list
- `PHASE0.md` - executable Phase 0 smoke contract and exact file paths
- `PHASE1.md` - Phase 1 scaffold contract and backend interface
- `NEXT_STEPS.md` - immediate bakeoff plan and success criteria
- `REFERENCES.md` - candidate models, papers, and product baselines
- `HARDWARE.md` - current local hardware notes and eGPU implications
- `AUTOMATION.md` - Bert/Gonzo cadence, phase-gate releases, and update format

## Phase 0 Smoke

Run from this folder:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 scripts/smoke_pipeline.py --create-fixture
```

This generates a deterministic synthetic fixture and writes the smoke outputs under `runs/phase0_smoke/`. The transform is a stub; it proves IO, diagnostics, and the untouched-plate contract only.

If `python3 -m venv` is unavailable on a minimal Linux install, use a local dependency target instead:

```bash
python3 -m pip install --target .deps -r requirements.txt
PYTHONPATH=.deps python3 scripts/smoke_pipeline.py --create-fixture
```

## Phase 1 Scaffold

After creating the fixture:

```bash
python3 cli/run_phase1.py --config configs/phase1_stub.json
```

With the local dependency target fallback:

```bash
PYTHONPATH=".deps:." python3 cli/run_phase1.py --config configs/phase1_stub.json
```

This writes the same trusted output family under `runs/phase1_scaffold/` and records config, input hashes, backend metadata, and output paths in `job.json`. The current backend is still a stub; the next Phase 1 step is replacing it with the first real relight/harmonize model while preserving the CLI and output contract.

## Local UI

For fast single-frame iteration, run the browser UI:

```bash
python3 -m pip install --target .deps -r requirements.txt
PYTHONPATH=".deps:." python3 ui/local_app.py
```

Then open:

```text
http://127.0.0.1:7865
```

The UI supports drag/drop or browse for A-side CG, B-side plate, optional matte, sequence-shaped multi-file uploads, GPU selection via `nvidia-smi`, PCT-Net artist controls, contact-sheet viewing, and single-output inspection. See `docs/LOCAL_UI.md` for Windows launch notes and current EXR/ACEScg status.

## Core Contract

```
CG RGBA + plate + alpha/matte -> background-conditioned relight/harmonize -> adjusted CG only -> normal over original plate
```

The plate remains untouched except for explicit, inspectable interaction passes such as contact shadows, edge spill, or shadow/reflection contributions.
