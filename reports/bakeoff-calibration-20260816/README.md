# Bakeoff Scorer — Build + First Calibration Anchor (2026-08-16, Gonzo)

Bert locked the packet and handed the GPU lane to me. This is the scorer built
to spec from `reports/model-landscape-20260816/BAKEOFF_PROTOCOL.md`, plus the
one calibration point available without spending a single GPU-second: yesterday's
IC-Light FBC run is real backend output and can be scored retroactively.

Tool: `scripts/score_bakeoff.py`. Preflight: RTX 3080 Ti visible, driver
610.57.04, **11.63 GiB** to PyTorch, 376 MiB in use.

## Self-test (runs on every invocation, before any candidate number)

Four ground-truth recovery checks on constructed cases. **All passed.**

| case | Axis 1 grad_struct_corr | Axis 2 mean_abs_change |
|---|---|---|
| legit relight (gain + tint, identity intact) | 0.9967 | 0.02870 |
| identity destroyed (blur, stats re-matched) | 0.2704 | 0.08492 |
| neglect (exact no-op) | 1.0000 | 0.00000 |

Axis 1 separates destruction from a legitimate relight, stays blind to global
gain, and Axis 2 reads exactly zero on a no-op.

## Bug found in my own Axis 2 before quoting it

First implementation compared `adjusted_fg` (a foreground image) against
`raw_a_over_b` (a composite) across the whole mask. That is apples to oranges at
partial-alpha edges, where the two are definitionally different:

| comparison | mean abs change |
|---|---|
| adjusted_fg vs raw composite (**wrong**) | 0.06534 |
| final_comp vs raw composite (**correct**) | 0.04046 |
| restricted to alpha > 0.99 — both variants | 0.04782 (identical) |

The inflation was **+62%**. What identified it: at alpha > 0.99 the two variants
agree *exactly*, which is only possible if the discrepancy lives entirely in the
edge blend rather than in the backend. Axis 2 now compares composite to
composite and additionally reports a core-alpha (>0.99) variant as a standing
robustness check.

## First calibration anchor — IC-Light FBC conservative (the control)

| axis | value | reference |
|---|---|---|
| Axis 0 `plate_untouched` max abs delta outside alpha | **0.003922** | tolerance 0.012 (`configs/phase2_gate.json`); uses ~33% of budget — **passes** |
| Axis 1 identity `grad_struct_corr` | **0.9487** | destroyed 0.27, legit 0.997, no-op 1.00 |
| Axis 2 change vs raw, in-mask | **0.04046** | core-alpha 0.04782, p95 0.1882 |

53,655 mask pixels, 2,017,995 outside-alpha pixels.

## This corrects my verdict from yesterday

On 2026-08-16 09:00 I wrote that the conservative transfer's composite was
"visually almost the raw A-over-B baseline" with "only mild darkening/cooling
apparent," and in the channel I later used it as the worked example of
**Neglect**. The measurement does not support that label.

Axis 2 reads 0.0405 in-mask, 0.0478 on core alpha, p95 0.188 — a mean ~4% shift
across the creature with a tail near 19%. That is **larger** than the
constructed case I built to represent a clearly *visible* legitimate relight
(0.0287). The conservative transfer is not sitting at the no-op end of the axis.

So the failure mode is not "it did nothing." It changed the image by a
measurable, non-trivial amount, kept identity largely intact (0.9487), and
**still did not look better**. That is a different and more awkward problem than
Neglect: the change is real but not *right*. Whatever tuning follows should be
aimed at direction and plausibility, not at turning up a strength dial that is
already doing more than my eye credited it for.

Practical consequence for the packet: had I set the Axis 2 floor from my visual
impression, I would have put it above 0.04 and disqualified a candidate that
does in fact change the image. Calibrating from measurement rather than
impression paid for itself on the first data point.

## Still not established

- **One anchor is not a calibration.** Thresholds remain unset, deliberately.
  Two more arms (DreamLight SD1.5, DreamLight FLUX) are needed before any
  pass/fail number is defensible.
- Axis 1 is necessary, not sufficient. A backend that hallucinates *new* high
  frequency detail could hold gradient correlation while destroying the monster.
  Bert's mandatory semantic bark/ember review stands and is not replaceable by
  either scalar.
- Axis 2 measures magnitude of change, not correctness of change. Nothing here
  says the direction is right — the finding above is precisely that it is not.
- n = 1 fixture, 1 frame, 1 seed (42).
- No preference vote has been taken. No candidate has advanced.
