# Latent Merge

Project channel: `#latent-merge` planned.
Origin: Discord `#project-planning`, 2026-05-20.

## Files

- `PROJECT_MEMORY.md` - current project synthesis and decision state
- `SPEC_DRAFT.md` - current aggressive v0 spec, gates, timeline, and risk list
- `PHASE0.md` - executable Phase 0 smoke contract and exact file paths
- `NEXT_STEPS.md` - immediate bakeoff plan and success criteria
- `REFERENCES.md` - candidate models, papers, and product baselines
- `HARDWARE.md` - current local hardware notes and eGPU implications

## Phase 0 Smoke

Run from this folder:

```bash
python scripts/smoke_pipeline.py --create-fixture
```

This generates a deterministic synthetic fixture and writes the smoke outputs under `runs/phase0_smoke/`. The transform is a stub; it proves IO, diagnostics, and the untouched-plate contract only.

## Core Contract

```
CG RGBA + plate + alpha/matte -> background-conditioned relight/harmonize -> adjusted CG only -> normal over original plate
```

The plate remains untouched except for explicit, inspectable interaction passes such as contact shadows, edge spill, or shadow/reflection contributions.
