# Latent Merge — Gonzo × Bert Workflow

The operating contract that stops the spiral: lost instructions, fake fixtures, token waste. `LOCKED.md` outranks this.

## Lanes (own it, don't duplicate)

**2026-06-17: Bert paused for this project (crons/heartbeats off, per Omid). Gonzo owns the full lane for now. Bert's responsibilities below are parked until Omid re-engages him.**

- Bert (VPS, no GPU): repo, CI/CD, packaging, docs, pipeline wiring behind `core/pipeline.py`, the Layer-2 scoring harness, release checkpoints. Keeps `cli/run_phase1.py` and the `job.json`/output contract stable.
- Gonzo (RTX 3080 Ti + display): GPU execution, real-plate fixture authoring, running backends, visual QA, contact sheets + sequence MP4s to the channel. Owns anything needing CUDA or eyes-on-pixels.

Rule: do not re-run or re-report the other agent's work. Need their output? Read it, don't regenerate it. One consolidated status per work cycle, not a stream of near-duplicates.

## Session protocol (every time)

- Start: read `LOCKED.md` + `NEXT_STEPS.md` (the live board). Confirm this cycle's fixtures satisfy L1 before running anything.
- End: preserve evidence in the appropriate durable place only when the run
  produced a real delta (for example, update `NEXT_STEPS.md`, append a daily
  note, or commit an artifact). Post at most one visual-forward status to
  `#latent-merge`, and only when the run completed useful work, found a new
  blocker needing a named owner, changed the forecast, or needs a decision.
  Otherwise stay silent; an unchanged gate is not a status event.

## Fixture law (enforces L1)

Every fixture carries `fixture.json` with `plate_provenance: "photographic" | "blender_smoke" | "synthetic"`. Only `photographic` feeds the quality gate. Reports must print provenance next to every case; a Blender/synthetic case may never appear in a "validation" PASS table without the SMOKE-ONLY label.

## Intake law: reference balls before anything else (2026-08-15)

**The first render against any new plate is `--asset ref_balls`.** Not Suzanne,
not a hero asset, not an identity test. The 18% matte + chrome pair reads three
independent things at once — tone curve agreement, indirect occlusion, and
HDRI/world alignment — and it reads them *before* a coloured or textured asset
compresses the shading range and hides the answer. This is mandatory for the two
Layer-2 `camera_original` cases, whose camera curves are not AgX and must be
matched to individually.

Origin: a saturated salmon placeholder concealed a renderer bug (light passing
through the ground plane onto the object's underside) across weeks of lighting
work. See `PHASE2_KNOWN_FAILS.md` entry 9 and
`reports/refball-tone-probe-20260815/`.

The regression fixture `tests/light_field_regression.py` renders **all** ground
modes every run, including the legacy `is_shadow_catcher` path, so the old
behaviour stays measurable as a baseline by construction rather than by policy.
Do not delete a ground mode from that test to make it green.

## The two gates (never conflate)

- Layer 1 = plumbing (plate untouched, no halo, runtime budget). Runs anywhere, including smoke fixtures. PASS here means "the pipe works," nothing about quality.
- Layer 2 = quality (blind A/B vs raw A-over-B on real plates, human preference). The only thing that lets a backend "pass."

## Token discipline

Read before you regenerate. One backend proven well beats three half-wired. Lead reports with an image/MP4 + a tight caption, not walls of text. No PASS theater: if the data is fake or the backend didn't really run, say so in one line and stop.
