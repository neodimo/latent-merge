# Automation Cadence

This cadence is for Gonzo/Bert coordination while the project follows the
aggressive Phase 1-4 timeline. `LOCKED.md`, `WORKFLOW.md`, and `NEXT_STEPS.md`
remain the source of truth for current gates and ownership.

## Latent-Merge Worker Pulse

The active cron pulse is a project worker, not a status reporter. Each run must
first identify what is genuinely new since the last Gonzo pulse, then finish one
bounded action that improves the project state.

Run order:

- inspect repo/GitHub state, `LOCKED.md`, `NEXT_STEPS.md`, and the newest project
  memory entry;
- name the single current bottleneck or uncertainty;
- finish one scoped action in the active owner lane, such as a missing
  validation, small bug fix, issue update, comparison artifact, or stale
  bookkeeping cleanup;
- verify the action and resolve every generated artifact as committed,
  intentional scratch, or explicit cleanup;
- post to `#latent-merge` only when the run completed useful work, found a new
  blocker needing a named person, changed the forecast, or needs a decision.

While issue #3 is waiting on DiMo's CC0 panorama-crop L1 ruling, do not keep
re-running the same photographic intake validator or CUDA preflight unless new
input arrived. Useful work in that state is limited to real new evidence,
cleanup, or making the next run less likely to repeat stale pulses.

Morning runs should state today's concrete gate and the most valuable thing
DiMo can run or review after the worker action is complete. Afternoon runs
should close or re-scope stale commitments and leave the next run's target
evidence-based.

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

Every project-channel post should lead with what changed since the last pulse,
then include the completed action, evidence/artifact/commit/PR, current
implication, and one named next owner. If nothing changed and no useful action
landed, stay silent.

Example:

```text
Phase 1 status: the pipe now takes plate + CG + alpha, writes an adjusted foreground, and composites it back over the untouched plate. In normal terms, we have the plumbing that proves Nuke can stay in control of the final composite. The current color adjustment is still a stub, so the next real win is replacing that stub with IC-Light or another harmonization model.
```

## Bert/Gonzo Lane Split

- Bert: repo structure, GitHub hygiene, reproducible CLI, docs, release notes, CI/checks, external research, cron summaries.
- Gonzo: local Nuke/Linux/Windows validation, GPU/runtime checks, media fixtures, local model runs, artist-facing failure notes.
- Shared: model selection, gate decisions, and whether a result is worth moving forward.
