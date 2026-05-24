# Automation Cadence

This cadence is for Bert/Gonzo coordination while the project follows the aggressive Phase 1-4 timeline.

## Daily Work Pulse

Weekdays at 9:15 AM Pacific, Bert should run a short project pulse:

- pull current repo state
- check the active phase and next gate
- run the smallest useful verification command
- identify one concrete next task for Bert and one for Gonzo
- post a layman's update in Discord with high-level specifics

The update should answer:

- What changed?
- What does it mean in normal language?
- What is blocked?
- What can Omid run or review?

## Phase Gate Releases

Each phase completion should produce a lightweight release checkpoint. A release can be a GitHub release, tag, or clearly named branch artifact depending on readiness, but it must include:

- one command that runs from a clean checkout
- Windows and Linux notes for an RTX 3080 Ti path where practical
- expected inputs and outputs
- a short layman's summary of what the model/pipeline is doing
- known limitations and failure cases

Release checkpoints:

- Phase 1: 2026-05-31 - reproducible real pipeline scaffold and selected first backend path
- Phase 2: 2026-06-07 - 10-case failure inventory plus at least one short proxy sequence
- Phase 3: 2026-06-14 - usable alpha surface, likely CLI/service before Nuke polish
- Audit pack: 2026-06-19 - clean install/run instructions, regression checks, benchmarks, limitations

## Communication Standard

Keep updates plain but specific. Avoid model jargon without translating it.

Example:

```text
Phase 1 status: the pipe now takes plate + CG + alpha, writes an adjusted foreground, and composites it back over the untouched plate. In normal terms, we have the plumbing that proves Nuke can stay in control of the final composite. The current color adjustment is still a stub, so the next real win is replacing that stub with IC-Light or another harmonization model.
```

## Bert/Gonzo Lane Split

- Bert: repo structure, GitHub hygiene, reproducible CLI, docs, release notes, CI/checks, external research, cron summaries.
- Gonzo: local Nuke/Linux/Windows validation, GPU/runtime checks, media fixtures, local model runs, artist-facing failure notes.
- Shared: model selection, gate decisions, and whether a result is worth moving forward.
