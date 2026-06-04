# Phase 2 Evaluation Gate

Gate date: 2026-06-07 EOD.

## Goal

Prove that the project can evaluate real harmonization results repeatably before adding more model breadth.

Phase 2 is not a new-backend milestone. It is the evaluation and user-surface lock for the first practical workflow:

```text
artist provides A-side CG + B-side plate + optional matte -> packaged UI run -> saved outputs + review sheet
```

## Locked User Surface

The locked Phase 2 user surface is the packaged local UI.

Deliver and defend:

- GitHub release binaries for Linux and Windows.
- The local browser UI launched by those binaries.
- The same output family already used by the CLI: adjusted foreground, final comp, diagnostics, and job metadata.

The CLI remains the reproducibility and automation harness, but it is not the Phase 2 user surface. Notebooks and Nuke/service integration are out of scope for this gate.

Reasoning:

- The release pipeline already ships UI binaries, so Omid can test real plates without local Python setup.
- Phase 2 scoring needs fast visual comparison and artifact review, which matches the UI better than a notebook or service.
- The CLI is still useful for smoke tests, baselines, and scripted case runs, but it is a developer surface.

## Acceptance Checklist

- 10 varied cases tested and recorded in the scoring sheet.
- At least 1 short proxy sequence tested for flicker.
- Runtime, memory, and variance baselines committed.
- Explicit known-fail list committed.
- Packaged UI behavior treated as the user-facing contract for this gate.

## Scoring Shape

Each case should record:

- Case ID and input fixture.
- Backend and settings.
- Identity preserved.
- Integration improved.
- Plate untouched.
- Edge behavior acceptable.
- Flicker result for sequence cases.
- Runtime and memory notes.
- Known-fail reason, if any.

