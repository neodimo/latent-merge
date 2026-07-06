# Latent Merge — Gonzo × Bert Workflow

The operating contract that stops the spiral: lost instructions, fake fixtures, token waste. `LOCKED.md` outranks this.

## Lanes (own it, don't duplicate)

**2026-06-17: Bert paused for this project (crons/heartbeats off, per Omid). Gonzo owns the full lane for now. Bert's responsibilities below are parked until Omid re-engages him.**

- Bert (VPS, no GPU): repo, CI/CD, packaging, docs, pipeline wiring behind `core/pipeline.py`, the Layer-2 scoring harness, release checkpoints. Keeps `cli/run_phase1.py` and the `job.json`/output contract stable.
- Gonzo (RTX 3080 Ti + display): GPU execution, real-plate fixture authoring, running backends, visual QA, contact sheets + sequence MP4s to the channel. Owns anything needing CUDA or eyes-on-pixels.

Rule: do not re-run or re-report the other agent's work. Need their output? Read it, don't regenerate it. One consolidated status per work cycle, not a stream of near-duplicates.

## Session protocol (every time)

- Start: read `LOCKED.md` + `NEXT_STEPS.md` (the live board). Confirm this cycle's fixtures satisfy L1 before running anything.
- End: update `NEXT_STEPS.md` (what moved, what's blocked, who's next), append a daily note (`memory/YYYY-MM-DD.md`), post ONE visual-forward status to #latent-merge.

## Fixture law (enforces L1)

Every fixture carries `fixture.json` with `plate_provenance: "photographic" | "blender_smoke" | "synthetic"`. Only `photographic` feeds the quality gate. Reports must print provenance next to every case; a Blender/synthetic case may never appear in a "validation" PASS table without the SMOKE-ONLY label.

## The two gates (never conflate)

- Layer 1 = plumbing (plate untouched, no halo, runtime budget). Runs anywhere, including smoke fixtures. PASS here means "the pipe works," nothing about quality.
- Layer 2 = quality (blind A/B vs raw A-over-B on real plates, human preference). The only thing that lets a backend "pass."

## Token discipline

Read before you regenerate. One backend proven well beats three half-wired. Lead reports with an image/MP4 + a tight caption, not walls of text. No PASS theater: if the data is fake or the backend didn't really run, say so in one line and stop.
