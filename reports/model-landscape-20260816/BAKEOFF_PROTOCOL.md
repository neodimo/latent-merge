# Proposed Bakeoff Scoring Protocol — 2026-08-16 (Gonzo)

**Status: proposed, not adopted.** Bert asked for approval of a replacement
bakeoff slate and offered an identity gate: bark topology, ember placement,
silhouette, and plate pixels outside alpha must survive. I agree with the shape.
This document is the scoring half, written before anything runs, because a
four-way bakeoff judged by eye afterwards selects a favourite instead of
measuring a winner.

## Finding: the identity check we already have cannot do this job

`scripts/assert_harmonization_output.py` gates foreground identity with
`identity_delta = mean(|adjusted - cg|)` inside alpha, upper-bounded by
`--max-identity-delta` (default **0.75**).

I ran three constructed cases with known ground truth against the real sh009 CG
foreground (53,655 mask pixels). Probe: `identity_metric_probe.py` in this
directory.

| case | mean_abs_delta (current gate) | grad_struct_corr (proposed) |
|---|---|---|
| A legitimate relight (gain + warm tint, identity intact) | 0.02870 | 0.9967 |
| B identity destroyed (structure blurred, mean/std re-matched) | 0.08492 | 0.2704 |
| C neglect (exact no-op) | 0.00000 | 1.0000 |

Two independent failures of the current metric:

1. **It has the wrong sign of sensitivity.** Mean absolute difference is
   maximally sensitive to a global exposure/tint shift — which is the *desired*
   output of a relight — and comparatively blind to structural destruction that
   preserves the global level. It scores the legitimate relight as a *larger*
   identity violation than it scores a no-op, which is backwards.
2. **At the default threshold it is inert.** The worst case here scores 0.085
   against a 0.75 limit — roughly 9x of headroom. A six-pixel gaussian blur that
   obliterates every bark and ember detail passes the gate comfortably. So does
   everything else. On this fixture the check cannot fail anything.

And the structural trap: **the no-op scores a perfect 0.0.** A backend that does
nothing wins the identity gate outright. That is precisely how yesterday's
conservative IC-Light transfer produced a passing run and no progress.

## Proposed two-axis gate

Identity alone is unsatisfiable in the useful direction — it is trivially
maximised by changing nothing. Every candidate must clear **both** axes.

**Axis 1 — identity retained (upper failure: Suppression).**
Gradient-magnitude structure correlation inside alpha, adjusted foreground vs
original CG. Blind to global gain/tint, sensitive to structure loss: it
separates A (0.997) from B (0.270) cleanly where the current metric does not.

**Axis 2 — lighting actually changed (lower failure: Neglect).**
Magnitude of change of the final composite against the **raw A-over-B baseline**
must exceed a floor. This axis does not currently exist anywhere in the repo,
and it is the one that would have failed yesterday's run.

**Axis 0 — hard pre-filter, binary, no judgement.**
`plate_untouched` outside alpha, already implemented in
`scripts/phase2_rejection_checks.py:158`. Any candidate that fails is
disqualified before a human looks at an image. This is where the L2 exposure
sits for the full-frame editors (Flux Kontext, and therefore LooseRoPE).

Map to yesterday's result as a sanity check: conservative transfer passes Axis 1,
fails Axis 2. Raw model foreground fails Axis 1. Neither is a Layer-2 candidate,
which matches the pixel verdict I wrote by eye.

## What this probe does NOT establish

- **Thresholds are not calibrated.** Three constructed points is not a
  calibration. No pass/fail number should be quoted until the metric has been
  run across real backend outputs.
- **Gradient-structure correlation is necessary, not sufficient.** Gaussian blur
  is one specific mode of destruction. A backend that *hallucinates new* high
  frequency detail — the glossy gold speculars IC-Light produced — could hold a
  moderate gradient correlation while still destroying identity. Bark topology
  and ember placement are semantic claims that this scalar does not encode.
- **n = 1 fixture, 1 frame.** Everything here is sh009.
- Axis 2 has no implementation yet; it is a specification, not code.

Applying the 2026-08-15 lesson deliberately: this probe is the ground-truth
recovery test, and it is why the numbers above are presented as evidence that
the *old* metric fails rather than as a validated new instrument.
