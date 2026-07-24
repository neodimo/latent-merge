# Automation Cadence

This cadence is for the latent-merge worker pulse after the 2026-06-17 reset.
`LOCKED.md`, `WORKFLOW.md`, and `NEXT_STEPS.md` remain the source of truth for
current gates and ownership.

## Latent-Merge Worker Pulse

The active cron pulse is a project worker, not a status reporter. Each run must
first identify what is genuinely new since the last Gonzo pulse. Finish one
bounded action only when new evidence or a real project-state improvement is
available; an unchanged external gate is a valid silent no-op, not a reason to
manufacture cleanup.

Run order:

- inspect repo/GitHub state, `LOCKED.md`, `NEXT_STEPS.md`, and the newest project
  memory entry;
- name the single current bottleneck or uncertainty;
- if evidence supports it, finish one scoped action in the active owner lane,
  such as a missing validation, small bug fix, issue update, comparison
  artifact, or stale bookkeeping cleanup;
- verify the action and resolve every generated artifact as committed,
  intentional scratch, or explicit cleanup;
- post to `#latent-merge` only when the run completed useful work, found a new
  blocker needing a named person, changed the forecast, or needs a decision.

While issue #3 is waiting on DiMo's CC0 panorama-crop L1 ruling, do not keep
re-running the same photographic intake validator or CUDA preflight unless new
input arrived. Useful work in that state is limited to real new evidence,
cleanup, or making the next run less likely to repeat stale pulses. Once those
surfaces are exhausted, end silently and inspect issue #3 first on the next run.

Morning runs should state today's concrete gate and the most valuable thing
DiMo can run or review after the worker action is complete. Afternoon runs
should close or re-scope stale commitments and leave the next run's target
evidence-based.

## Release Gate

The old date-driven phase-release schedule is retired. Synthetic, Blender-smoke,
and operational-readiness milestones do not trigger a packaged release.

Publish a release checkpoint only after the first accepted photographic Layer-2
gate: the locked real-plate fixture set exists, raw A-over-B vs backend evidence
is recorded, the plate-untouched contract holds, and DiMo has a preference
decision. This matches GitHub issue #6 and prevents packaging stale or
non-quality evidence.

That release should include:

- one command that runs from a clean checkout
- Windows and Linux notes for an RTX 3080 Ti path where practical
- expected inputs and outputs
- a short layman's summary of what the model/pipeline is doing
- links to the exact fixtures/evidence and known limitations/failures

## Communication Standard

Keep updates plain but specific. Avoid model jargon without translating it.

Every project-channel post should lead with what changed since the last pulse,
then include the completed action, evidence/artifact/commit/PR, current
implication, and one named next owner. If nothing changed and no useful action
landed, stay silent.

Example:

```text
Since the last pulse, <specific state or measurement changed>. Completed <bounded action>; evidence: <artifact, commit, PR, or exact check>. This means <current implication, including any remaining uncertainty>. Next owner: <one person> for <one concrete action>.
```

The example is structural rather than a reusable status claim. Workers must
replace its delta, evidence, implication, and owner with facts from the current
run.

## Bert/Gonzo Lane Split

- Bert is paused on this project until Omid re-engages him.
- Gonzo currently owns active worker pulses, GPU/runtime checks, media fixtures,
  local model runs, visual QA, docs cleanup, and project bookkeeping.
- Parked Bert lane: repo structure, GitHub hygiene, reproducible CLI, docs,
  release notes, CI/checks, external research, and Layer-2 scoring harness.
- Shared: model selection, gate decisions, and whether a result is worth moving forward.
