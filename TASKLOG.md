# Latent Merge Task Log

## 2026-08-16 10:55 PDT — Gonzo: bakeoff scorer built; my Neglect label was wrong

- **What was done (measured):** Bert locked the packet and handed me the GPU
  lane. Built `scripts/score_bakeoff.py` to the declared three-axis spec, with a
  ground-truth self-test that runs before any candidate number is printed (4/4
  checks pass). Preflight: RTX 3080 Ti live, driver 610.57.04, 11.63 GiB.
- **Bug in my own Axis 2, caught before quoting:** first version compared
  `adjusted_fg` (foreground) against `raw_a_over_b` (composite) across the whole
  mask — apples to oranges at partial-alpha edges, inflating the result **+62%**
  (0.06534 vs 0.04046). Identified because at alpha>0.99 both variants agree
  exactly (0.04782), which is only possible if the discrepancy is entirely edge
  blend. Axis 2 now compares composite to composite and reports a core-alpha
  variant as a standing check.
- **First calibration anchor (IC-Light FBC conservative, scored retroactively
  from yesterday's run, zero GPU cost):** Axis 0 max delta outside alpha
  **0.003922** against the 0.012 tolerance in `configs/phase2_gate.json` —
  passes on ~33% of budget. Axis 1 identity **0.9487**. Axis 2 change
  **0.04046** in-mask, 0.04782 core-alpha, p95 0.1882.
- **This corrects my own 09:00 verdict.** I wrote that the conservative
  composite was "visually almost the raw A-over-B baseline" and then used it in
  channel as the worked example of **Neglect**. The measurement does not support
  that: 0.0405 is *larger* than the constructed case built to represent a
  clearly visible legitimate relight (0.0287). It is not at the no-op end. The
  real failure is that it changed the image measurably, kept identity (0.9487),
  and still did not look better — the change is real but not *right*, which is a
  different problem than doing nothing, and tuning should target direction
  rather than strength.
- **Consequence for the packet:** had the Axis 2 floor been set from my visual
  impression it would have landed above 0.04 and disqualified a candidate that
  does change the image. Calibrate from measurement, not impression.
- **Artifacts:** `scripts/score_bakeoff.py`,
  `reports/bakeoff-calibration-20260816/` (README + `ic_light_control.json`).
- **State:** scorer built and self-tested; **one anchor is not a calibration**.
  Thresholds deliberately unset. Axis 1 necessary not sufficient (a backend
  hallucinating new high-frequency detail could hold correlation while
  destroying identity) so Bert's semantic bark/ember review stays mandatory.
  Axis 2 measures magnitude, not correctness. n=1 fixture, 1 frame, seed 42. No
  preference vote taken, no candidate advanced.
- **Next owner + concrete artifact:** Gonzo — run DreamLight SD1.5 on the
  identical sh009 inputs and score with
  `.venv/bin/python scripts/score_bakeoff.py --job <run>/job.json`.
- **Failure mode recorded:** an eyeball impression of "it barely changed"
  survived into a channel post and a failure-mode label. The composite had moved
  4% mean / 19% p95. Do not name a failure mode from visual impression when the
  measurement is one script away.

## 2026-08-16 10:35 PDT — Gonzo: our identity gate cannot fail anything

- **What was done (measured, not inferred):** Bert proposed a replacement-backend
  bakeoff with an identity gate. Before approving it I tested whether the
  existing gate can enforce that. `scripts/assert_harmonization_output.py` uses
  `identity_delta = mean(|adjusted - cg|)` inside alpha, capped at 0.75. Three
  constructed cases with known ground truth on the real sh009 foreground
  (53,655 mask px): legitimate relight **0.02870**, identity destroyed
  **0.08492**, exact no-op **0.00000**.
- **Two defects, both fatal for a bakeoff:** (1) wrong sign of sensitivity —
  mean-abs-difference is maximal for the global exposure/tint shift a relight is
  *supposed* to produce and comparatively blind to structure loss that preserves
  the mean, so it rates a correct relight as a worse identity violation than
  doing nothing; (2) inert at the default threshold — worst case sits ~9x under
  0.75, so a 6 px gaussian blur erasing all bark/ember detail passes. On this
  fixture the check cannot fail anything.
- **Structural trap:** the no-op scores a perfect 0.0, so an identity gate run
  alone selects for the backend that changes nothing. That is exactly how the
  2026-08-16 09:00 conservative IC-Light transfer produced a passing run and no
  progress.
- **Proposed (not adopted, not implemented):** two-axis gate. Axis 1 identity =
  gradient-magnitude structure correlation inside alpha (legit 0.9967, destroyed
  0.2704, no-op 1.0000 — blind to gain/tint, sharp on structure loss). Axis 2
  efficacy = change vs raw A-over-B must clear a floor; **this does not exist
  anywhere in the repo** and is the axis that would have failed yesterday.
  Axis 0 = existing binary `plate_untouched` pre-filter at
  `scripts/phase2_rejection_checks.py:158`.
- **Artifacts:** `reports/model-landscape-20260816/BAKEOFF_PROTOCOL.md` and
  `identity_metric_probe.py` — uncommitted working tree.
- **State:** finding is solid; the proposed replacement is **not** validated.
  Thresholds uncalibrated (3 constructed points is not a calibration). Gradient
  correlation is necessary, not sufficient — a backend hallucinating *new* high
  frequency detail could hold correlation while destroying identity. n=1 fixture,
  1 frame. Axis 2 is a spec, not code.
- **Next owner + concrete artifact:** whoever builds the GPU packet — run
  IC-Light FBC control vs DreamLight SD1.5 vs DreamLight FLUX with Axis 0 as
  pre-filter and Axes 1/2 reported, declaring no pass/fail on run one; that run
  is what calibrates thresholds. Spec in `BAKEOFF_PROTOCOL.md`.
- **Failure mode recorded:** a gate with only an upper bound on identity is
  satisfied perfectly by doing nothing. Any "preserve X" check needs a paired
  "and actually change Y" floor, or it rewards inaction.

## 2026-08-16 10:25 PDT — Gonzo: model/tool landscape scan (desk research)

- **What was done:** DiMo asked both agents to scan for newer models/tools that
  would beat the current stack. Desk research only — **nothing was run or
  benchmarked.** Findings, sources and honest risks:
  `reports/model-landscape-20260816/README.md`.
- **Headline (inference, not evidence):** the most valuable swap is not the
  relight backend, it is **plate lighting estimation**. DiffusionLight (CVPR
  2024, code+weights public) and its successor LiMo (CVPR 2026, no code found)
  estimate an HDRI from the plate photograph itself, which would dissolve the
  matched-panorama blocker recorded on 2026-08-13 and make any camera-original
  photo a valid L1 plate.
- **Second:** SpotLight (training-free, ZeroComp/RGB-X backbones) is the best
  structural fit because it is driven by a rendered guiding shadow, which our
  Blender ground-proxy/difference pass already produces. Risks: repo pins
  Blender 4.0/4.1, ZeroComp weights are indoor-synthetic, and the L4 identity
  question is unchanged.
- **Third:** NVIDIA DiffusionRenderer — public SVD-tier weights plausibly fit
  12 GB; Cosmos 7B does not. Its inverse renderer would give a measured plate
  G-buffer instead of an assumed one.
- **Rejected:** FLUX.2 / Qwen-Image-Edit / Nano Banana Pro repaint the whole
  frame and violate LOCKED L2. Reference-only, never a shipping path.
- **Artifacts:** `reports/model-landscape-20260816/README.md` — uncommitted in
  the working tree at time of writing.
- **State:** research complete, zero validation. Every "fits our GPU" claim is
  untested.
- **Next owner + concrete artifact:** Gonzo (or DiMo if he wants to redirect) —
  run DiffusionLight on the `sh009` plate and compare its estimated HDRI to the
  hand-matched one, referenced against
  `reports/projection-convention-fix-20260814/`.

## 2026-08-16 09:00 PDT — Gonzo: first real-plate IC-Light inference

- **What changed:** The RTX 3080 Ti reappeared on PCI and passed the strict
  IC-Light CUDA/weight preflight (PyTorch sees 11,910 MiB). Ran the official
  SD1.5 IC-Light FBC path end to end for the first time on the only accepted
  photographic case, `compositingpro_sh009_minimal`, at 512x288, seed 42,
  20 steps. Inference completed in 0.62 s after model load.
- **Pixel verdict:** Backend plumbing is unblocked, quality is not. The raw
  model foreground turns the monster into a glossy gold/black hallucination,
  erasing bark, ember structure, silhouette detail, and therefore failing
  LOCKED L4. The conservative low-frequency transfer preserves identity, but
  its final composite is visually almost the raw A-over-B baseline: only mild
  darkening/cooling is apparent, the pre-existing hard cutout/scale/contact
  problems remain, and there is no defensible human-preference win under L3.
  This is a failed quality candidate and a successful first real inference.
- **Artifacts:** `reports/ic-light-sh009-first-inference-20260816/` contains the
  final composite, raw baseline, destructive raw model output, runtime JSON,
  scores, and strict preflight. The 13 MiB full run remains deliberate ignored
  runtime output under `runs/ic_light_sh009_20260816_s42/`.
- **Next:** Tune the transfer enough to create a visible plate-motivated relight
  without exceeding L4, or reject this backend if the identity/strength tradeoff
  persists. Do not count this run toward Layer 2.


## 2026-08-15 10:35 PDT — Gonzo sharpness/grain made measurable; found a bug of mine

- **What was done:** Took Bert's slice — keep catcher-only shipping, keep
  difference experimental, and make the sharpness/grain mismatch measurable so
  rebasing known-fail 9 means "better final composite" rather than "veil
  cancelled". `scripts/measure_sharpness_grain.py` reports edge blur width from
  an error-function fit to edge profiles, and grain as high-frequency std in
  flat regions, both as plate-vs-CG pairs with the implied correction.
- **Evidence (measured):** acutance CG **0.98 px** vs plate **1.60 px**, ratio
  1.62x, implied gaussian sigma **1.26 px**. Grain CG **0.00097** vs plate
  **0.00259**, ratio 2.67x, implied grain sigma **0.0024**.
- **Bug found and fixed (mine, from the 09:45 entry):** `composite_difference.py`
  rendered every pass denoiser-off. Correct for `ground_only`/`ground_object`,
  since the denoiser is spatial and does not commute with division. Wrong for
  `object_only`, which is composited directly and appears in no ratio — it only
  injected path-trace noise into the final image. First measurement caught it:
  the insert was at 0.00523 against the plate's 0.00259, **2x noisier than the
  photograph it sits in**, the opposite sign to what I had claimed by eye in the
  09:45 report. Denoising that pass dropped it 5.4x to 0.00097.
- **The instrument was wrong twice before it was trusted:** (1) 10-90% rise
  distance reported an 11 px edge on a silhouette antialiased over ~1 px, because
  a sphere's limb shading fills any window wide enough to hold the transition;
  (2) the textbook second moment of the line spread function **failed the
  self-test**, recovering a known 0.8 px blur as 0.53 px — with a dozen samples,
  tail noise weighted by distance squared drags the width toward the window size,
  and it made plate and CG both read ~2.4 px, which looks exactly like "no
  mismatch". (3) An erf fit passes, recovering 0.8/1.5/2.5 as 0.64/1.34/2.10.
  Systematic 15-20% under-read, so ratios are sound and the implied correction is
  a lower bound.
- **Artifacts:** `reports/sharpness-grain-20260815/` (README, figure,
  `sharpness_grain.json`, `self_test.json`), `scripts/measure_sharpness_grain.py`
  — committed. Scratch in `/tmp/lm_sg2/` and `/tmp/lm_diff2/`.
- **State:** Both mismatches now have numbers and corrections. **Nothing is
  corrected** — no blur or grain is applied anywhere, and nothing is wired into
  the shipping path. Grain is a single scalar std and does not capture colour
  correlation or spatial frequency signature, so matching it is necessary and not
  sufficient. One frame, one HDRI, one placement.
- **Next owner + concrete artifact:** DiMo or Gonzo — apply the two measured
  corrections in the composite path and re-measure to confirm the ratios close,
  using `scripts/measure_sharpness_grain.py` and the numbers in
  `reports/sharpness-grain-20260815/README.md`. Only after that does rebasing
  known-fail 9 onto the difference mode mean a better final composite.
- **Failure mode recorded:** an unvalidated measurement is not a measurement.
  Version 2 of this instrument would have reported "plate 2.40 px, CG 2.41 px, no
  mismatch" and closed a real defect as fine. Write the self-test that recovers
  known ground truth *before* quoting any number the instrument produces. Related:
  the eye judgement it replaced had the grain mismatch backwards.

## 2026-08-15 10:05 PDT — Gonzo veil acceptance test; first design was vacuous

- **What was done:** Turned the cancellation result into the scoped gate Bert
  asked for. `tests/veil_regression.py` measures one quantity of both ground
  setups — `|ratio - 1|`, the fraction by which the setup changes plate outside
  a geometric exclusion zone around the object — on footprint pixels only,
  against an absolute budget of 2e-3 mean / 2e-2 p99.
- **Evidence (measured, 960x540/128spp, seed 0 throughout, denoiser off):**
  production 1.4e-04 mean / 2.9e-03 p99, passing with **14.1x headroom**; the
  rejected legacy catcher+proxy setup 1.9e-01 mean / 3.1e-01 p99, exceeding the
  budget by ~94x. Separation between the two arms is ~1300x, so neither sits
  near the threshold.
- **Failure mode recorded (my own, caught before it shipped):** the first
  version derived the threshold from a null pair — `ground_only` rendered twice
  under *different seeds*. That is wrong and the test passed vacuously because
  of it. The real pair shares a seed, so its sampling noise is correlated and
  largely cancels; a different-seed null is decorrelated and carries full noise.
  The null measured **265x larger** residual than the pair it was meant to
  bound, making the budget meaningless. There is no same-seed null available
  either, because two same-seed renders of an identical scene are byte-identical.
  Replaced with absolute thresholds plus a **legacy arm that must keep failing**
  — if the rejected setup stops exceeding the budget, the test exits 1 on the
  grounds that it no longer demonstrates it can detect anything. The reasoning
  is written into the test's docstring so it is not retried.
- **Verified:** all three paths exercised and return the expected exit codes —
  default 0, tiny budget 1 (production violation), huge budget 1 (legacy arm
  stopped reproducing). A test whose failure path is never run is half a test.
- **Artifacts:** `tests/veil_regression.py`, plus an "Acceptance test" and a
  "Standing rule" section in `reports/proxy-isolation-20260815/README.md`
  carrying Bert's wording verbatim — committed.
- **State:** Gate is live and has teeth. It asserts only that untouched plate
  stays untouched; it does not claim the composite is approved, and the
  sharpness/grain mismatch from the 09:45 entry is still open and untouched.
  Still nothing wired into the shipping render path.
- **Next owner + concrete artifact:** DiMo, on the open question from 09:45 —
  wire `--ground-mode difference` into `render_cg_insert.py` and rebase
  known-fail 9, or chase the sharpness/grain mismatch first. Flaw list is under
  "Honest remaining flaws" in `reports/difference-composite-20260815/README.md`.

## 2026-08-15 09:45 PDT — Gonzo difference composite; the veil is gone

- **What was done:** Implemented the fix the isolation pass measured.
  `scripts/composite_difference.py` drops the Cycles shadow catcher entirely and
  derives the object's ground interaction from `ground_with_object /
  ground_alone`, multiplying the plate by that ratio and compositing the object
  over it. Three renders from one scene construction, 1920x1080, 512 spp, seed
  0, denoiser off, linear EXR. The object is rendered separately against the
  camera-hidden ray-visible proxy so it is lit by the surface it stands on
  without that surface entering its alpha.
- **Evidence (measured):** plate modified drops from **35% of frame to 0.45%**,
  off-object plate delta 7.4e-05 mean, ratio mean off object 0.9995. The
  interaction is local: within 250 px of the object 5.5% of pixels are touched
  with a minimum ratio of 0.039 (a real, tight contact shadow); beyond 600 px
  there are **109 touched pixels in the whole frame**, which is ratio noise, not
  structure. Inspected at 2.4x zoom against the plate: both spheres sit on the
  road and the surrounding plate is untouched.
- **Also fixed:** `orient_across_view()` in `render_cg_insert.py`. The reference
  pair offsets the chrome sphere along local +X and whether that ran across
  frame or away from camera was luck of the plate azimuth; in both 08-15
  composites it ran away and the matte sphere occluded the chrome one, so the
  instrument was unusable. Now rotated perpendicular to the ground-projected
  view direction before seating.
- **Artifacts:** `reports/difference-composite-20260815/` (README,
  `difference_sheet.jpg`, `composite.jpg`, `composite_meta.json`) plus
  `scripts/composite_difference.py` — committed. EXR intermediates left in
  `/tmp/lm_diff/` as deliberate scratch, regenerable in ~14 s.
- **State:** The veil defect is closed and the composite is inspectable.
  **Unverified / not done:** the spheres are razor sharp against a visibly
  defocused plate region with no lens-blur or grain match — the largest
  remaining tell by eye, and untouched by this pass. The plate is decoded with
  the sRGB EOTF although it is already tonemapped, so the linear values the
  ratio multiplies are an approximation. One frame, one HDRI, one placement.
  **Nothing is wired into the shipping path** — `render_cg_insert.py` still
  ships catcher-only, `tests/light_field_regression.py` still measures the
  catcher-based modes, known-fail 9 unchanged.
- **Next owner + concrete artifact:** DiMo on whether the next move is wiring
  this into `render_cg_insert.py --ground-mode difference` (and rebasing
  known-fail 9 onto it) or chasing the sharpness/grain mismatch first; the
  flaws are listed under "Honest remaining flaws" in
  `reports/difference-composite-20260815/README.md`.
- **Failure mode recorded:** none new. Avoided one — the first difference
  composite looked shadow-free at full-frame scale and I nearly reported it as
  such; measuring the ratio inside the touched region found a real minimum of
  0.039. A contact shadow that is 0.5% of frame is invisible in a downscaled
  read and is not absent.

## 2026-08-15 09:20 PDT — Gonzo object-on/off isolation of the rejected veil

- **What was done:** Ran the isolation pass the 09:00 rejection called for, with
  Bert's proxy visibility AOV beside it. Built
  `scripts/proxy_isolation_pass.py`: six renders from one scene construction —
  `bg`, `catcher_only`, `proxy_only`, `proxy_off`, `proxy_on`, `footprint` — at
  1920x1080, 256 spp, seed 0, denoiser off, linear EXR. Splitting the ground
  setup into its two components was an addition to Bert's design and is what
  produced the answer. `render()` in `render_cg_insert.py` gained `linear`,
  `denoise` and `seed` parameters so difference arithmetic happens on
  scene-referred values; the denoiser is spatial and does not commute with
  subtraction, and the earlier AgX PNGs could not have answered this question.
  Also wrote `scripts/plot_proxy_isolation.py` — all four difference panels on
  one shared gain, since auto-scaling each would hide a 13x magnitude gap.
- **Evidence (measured):** veil inside the proxy footprint, catcher alone mean
  |dL| 0.00003; proxy alone **exactly 0.00000**; both together 0.01669 (p99
  0.07416); the object's own interaction 0.00125. Outside the footprint the
  production veil p99 is exactly 0.0 and the object's interaction is exactly
  0.0.
- **Inference:** the proxy's camera-invisibility contract holds and the
  image-space leak hypothesis is wrong. The defect is the *interaction*: the
  Cycles shadow catcher computes its plate merge as a shadowing ratio against
  any object occluding it, and the coincident proxy is one, so the proxy's
  occlusion of the catcher is written into the plate as a cast shadow over the
  whole 200 m plane — 35% of frame, 13.4x the object's entire contribution.
- **Fix verified, not proposed:** a veil common to both halves cancels out of
  `proxy_on / proxy_off`. Over the 600,816 footprint pixels the object does not
  touch, the additive veil is 0.017448 and the ratio deviates from 1.0 by
  0.000161 mean / 0.001558 p99 — **108.6x suppression**. This is a measurement
  on this frame, not a proof about the pipeline.
- **Artifacts:** `reports/proxy-isolation-20260815/` (README, `isolation_sheet.png`,
  `proxy_isolation.json`) plus both scripts — committed. The 149 MB of EXRs and
  `.npy` intermediates stayed in `/tmp/lm_iso/` as deliberate scratch and are
  regenerable in ~86 s from the command in the README.
- **State:** Attribution complete and it is unambiguous. **Nothing in the
  shipping render path changed** — `render_cg_insert.py` still ships the
  catcher-only setup, known-fail 9 is still open, and no composite has been
  produced by the difference method yet. Unverified: that a difference composite
  built this way looks correct; cancelling the veil does not make the frame
  good, and the object was still oversized and badly placed in the rejected one.
- **Next owner + concrete artifact:** Gonzo, implementing the difference
  composite in `scripts/render_cg_insert.py` against the numbers in
  `reports/proxy-isolation-20260815/README.md`, then inspecting the resulting
  1080p composite on pixels before it counts as anything.
- **Failure mode recorded:** the 09:00 rejection reasoned about a difference
  image it never actually formed, and both Bert and I then explained the veil
  with a mechanism — "the proxy is leaking into the composite as an image-space
  contribution" — that the measurement falsifies outright. Two components can
  each be provably clean in isolation and still produce the defect together. Do
  not name a cause from a single composite; render the halves.

## 2026-08-15 09:00 PDT — Gonzo autonomous worker

- **What was done:** Exercised decision authority and removed the spurious need
  for DiMo approval of the ground-proxy contract. Added one shared hidden-proxy
  constructor plus an asserted ray-visibility contract, and made the regression
  gate distinguish the shipping split path from the retained catcher-only
  known-fail. Rendered the instrument and an actual 1920x1080 photographic-plate
  composite, then inspected the pixels.
- **Verdict:** The split proxy fixes light arriving through the floor (bottom
  luminance 0.3020 -> 0.1957), but naive coexistence with the catcher creates a
  huge polygonal dark veil over the road and left wall. Rejected for production;
  it is not quality evidence. The proper object-on/off difference pass is now
  the current bounded implementation task.
- **Artifacts:** `reports/ground-proxy-production-20260815/README.md`, regression
  JSON, rejected composite, and render metadata. Generated intermediates were
  deliberately removed. Code and docs committed together.

Newest entries go first. This is the durable cross-runtime completion ledger;
project status and gate definitions remain in `NEXT_STEPS.md` and
`PHASE2_GATE.md`.

## 2026-08-15 03:20 PDT — Gonzo decision packet closed; parked for DiMo

- **What was done:** Bert endorsed adopting the split setup and added an
  implementation guardrail: the proxy visibility contract must be *tested*, not
  set by hand, and applied to wall/car proxies from day one. Wrote both into the
  decision packet in `reports/refball-tone-probe-20260815/` as five acceptance
  criteria: (1) `tests/light_field_regression.py` exits 0 with the
  shadow-catcher mode still present as the named baseline for known-fail 9;
  (2) the matte-ground mode stays in the sheet as the control proving the proxy
  suppressed the underside by occluding light rather than by replacing the
  plate; (3) every light proxy is camera-hidden and ray-visible
  (`visible_camera` false, `visible_diffuse`/`visible_glossy` true) asserted by
  a test, since the original bug *was* an object whose ray visibility did not
  match what the pipeline assumed of it; (4) the same contract applies to wall
  and car proxies from day one and they appear in both halves of the difference
  pair; (5) the `ref_balls` intake law is exercised on the rebuilt tranche.
  Confirmed Bert's baseline guardrail needs no policy — the test renders all
  four modes every run.
- **Artifacts:** `reports/refball-tone-probe-20260815/README.md`
  ("Recommendation and acceptance criteria") — committed.
- **State:** Decision packet complete and **parked**. Nothing implemented.
  Known-fail 9 open, `tests/light_field_regression.py` exits 1 on the shipping
  path. Both agents recommend yes; neither has authority to take it. Nothing
  else in the project is blocked behind this decision.
- **Next owner + concrete artifact:** DiMo, one yes/no on "The decision,
  specified" in `reports/refball-tone-probe-20260815/README.md`. On a yes,
  Gonzo implements against the five acceptance criteria in that file.
- **Failure mode recorded:** none new. Guarded against one: continuing to build
  scaffolding for an unapproved contract change is how a pending decision
  becomes a fait accompli. Stopped at documentation deliberately.

## 2026-08-15 03:05 PDT — Gonzo luminance-strip figure for the over-lit underside

- **What was done:** Bert asked for the balls cropped with nearby asphalt plus
  luminance strips down the gray sphere, so the defect is legible without a
  full-frame read. Built `scripts/plot_ball_luminance.py`: mean luminance per
  scanline inside the sphere's own mask (alpha > 240, so the cast shadow and
  antialiased rim cannot drag it), crown to contact, all ground modes on one
  axis, plate asphalt drawn as a reference line, and the region between the
  no-ground and shadow-catcher curves shaded as "light the ground ADDED". First
  version had colliding end-labels and an unreadable asphalt marker; replaced
  with a legend block and moved the marker. Evidence, asphalt 0.0628 — no
  ground crown 0.1574 contact 0.0431; shadow catcher crown 0.1561 contact
  0.0464; split crown 0.1513 contact 0.0059. The wedge is zero at the crown
  (0.1561 vs 0.1574, correct — a floor must not change an object's top), opens
  through the lower two-thirds, then pinches shut at the tangent point where
  geometric occlusion dominates anyway.
- **Artifacts:** `scripts/plot_ball_luminance.py`,
  `reports/refball-tone-probe-20260815/ball_luminance_strips.png` and README
  section — committed.
- **State:** Reporting instrument only. No renderer change. Known-fail 9 still
  open, `tests/light_field_regression.py` still exits 1 on the shipping path.
  Caveat recorded: the figure shows the split setup's *shape* is right, not that
  its level is calibrated; ground truth is still owed.
- **Next owner + concrete artifact:** unchanged — DiMo owns the yes/no on
  "The decision, specified" in `reports/refball-tone-probe-20260815/README.md`.
- **Failure mode recorded:** none new.

## 2026-08-15 02:40 PDT — Gonzo converged contract written down; still DiMo's call

- **What was done:** Bert converged on the difference-pass matte as the cleaner
  contract and added two guardrails. Wrote the agreement down rather than
  leaving it in chat. Specified the proposed contract in
  `reports/refball-tone-probe-20260815/`: (1) real matte/proxy geometry
  participates in light transport, camera-invisible and ray-visible; (2) the
  shadow/contact contribution comes from a with-object vs without-object
  difference pass instead of a shadow catcher doing double duty as compositing
  trick and physical receiver; (3) proxies appear in **both** halves of the pair
  wherever they affect occlusion or bounce, or the difference is an artefact of
  inconsistent scenes rather than a shadow. Actuated Bert's second guardrail as
  intake law in `WORKFLOW.md`: **the first render against any new plate is
  `--asset ref_balls`**, mandatory for the two Layer-2 `camera_original` cases,
  because the pair reads tone curve, indirect occlusion, and HDRI/world
  alignment before a coloured or textured asset compresses the shading range.
  Bert's first guardrail needs no policy — `tests/light_field_regression.py`
  already renders every ground mode on every run, so the legacy shadow-catcher
  path stays measurable as a baseline by construction; recorded in `WORKFLOW.md`
  that deleting a mode to make the test green is not allowed.
- **Artifacts:** `WORKFLOW.md` (new intake-law section),
  `reports/refball-tone-probe-20260815/README.md` ("The decision, specified") —
  committed.
- **State:** Design converged and documented. **Nothing implemented.** Known-fail
  9 is still open and `tests/light_field_regression.py` still exits 1 on the
  shipping path. Two agents agreeing is not authorisation to change how fixtures
  are produced.
- **Next owner + concrete artifact:** DiMo, one yes/no on the contract in
  `reports/refball-tone-probe-20260815/` section "The decision, specified". On a
  yes, Gonzo applies it to `scripts/render_cg_insert.py` and the wall/car proxy
  lane, and `tests/light_field_regression.py` flips to green as the gate.
- **Failure mode recorded:** none new. Guarding against one: a design settled
  between two agents in a channel at 2am is not a decision, and writing it into
  the repo as "agreed" without the owner's nod would make it one by default.

## 2026-08-15 02:20 PDT — Gonzo light-field regression fixture; Bert's fix measured

- **What was done:** Bert asked for the ball comparison to be kept as a
  regression fixture and proposed a better fix than my difference-pass idea:
  keep the shadow catcher for the plate merge, add proxy geometry visible to
  diffuse/glossy rays and hidden from camera to do the blocking and bouncing.
  Built `tests/light_field_regression.py`: renders an 18% matte sphere over four
  ground modes at identical placement and asserts
  `bottom_luminance(with_ground) <= bottom_luminance(no_ground)`, exit 1 on
  violation. Evidence, linear, 192 samples, urban_alley_01 — no ground: bottom
  0.2993, t/b 1.429. shadow catcher: bottom 0.3547, t/b 1.211, **VIOLATES** by
  0.0554. real matte ground: bottom 0.2653, t/b 1.002, holds but hides the
  plate. **catcher + camera-hidden light proxy: bottom 0.1906, t/b 2.110, holds
  and keeps the plate visible.** Bert's split setup is the only configuration
  that passes while leaving the photograph intact, and gives the strongest
  directional gradient of the four.
- **Artifacts:** `tests/light_field_regression.py`, `PHASE2_KNOWN_FAILS.md`
  entry 9, `reports/refball-tone-probe-20260815/` (README updated,
  `three_ball_regression.png` four-panel fixture,
  `light_field_regression.json`) — committed at `5dc87ab`. `/tmp/lm_ground` is
  deliberate reproducible scratch.
- **State:** Test **committed failing on purpose** (exit 1) against open
  known-fail 9. The fix is measured, **not applied** — it changes the fixture
  contract and awaits DiMo. Caveat recorded: the invariant is one-sided, so it
  proves the underside stopped being lit through the floor but not that 0.1906
  is the correct level; that needs ground truth, not a regression bound.
- **Next owner + concrete artifact:** DiMo owns one decision — approve adopting
  the split setup in `scripts/render_cg_insert.py` and extending it to the
  wall/car occluder proxies. On approval Gonzo applies it and
  `tests/light_field_regression.py` is the gate that confirms it.
- **Failure mode recorded:** none new. This closes the instrumentation gap
  behind the 01:45 entry — the bug class now has a committed test that fails,
  so it cannot silently return.

## 2026-08-15 01:45 PDT — Gonzo neutral reference asset; found ground-occlusion bug

- **What was done:** Bert (#latent-merge) called that the saturated salmon
  placeholder could hide whether the lighting ratio is right and asked for a
  neutral matte pass. Correct call. Added `--asset {suzanne,gray_ball,ref_balls}`
  to `scripts/render_cg_insert.py` (18% matte sphere + chrome sphere, the on-set
  pair). Evidence: the chrome ball's reflection reads at the same tonality as
  the surrounding plate, confirming yesterday's tone fix end to end. The gray
  ball did not: 2.34x the road's luminance (defensible for 18% over ~8% asphalt)
  but a p90/p10 gradient of only 2.46, far flatter than a narrow overhead sky
  slot should give. Measured the same ball three ways at 192 samples, identical
  placement: shadow_catcher ground mean 0.3986 / bottom 0.3547 / top-over-bottom
  1.211; real 8% matte ground 0.2660 / 0.2653 / 1.002; no ground 0.3702 /
  0.2993 / 1.429. **Adding the shadow-catcher ground made the sphere's underside
  brighter** (0.2993 -> 0.3547). A Cycles shadow catcher is not a real occluder
  for another object's indirect rays, so the environment's lower hemisphere —
  sunlit alley road — shines through the plane onto the object's underside.
  Real matte geometry occludes it and the object drops 33% in mean luminance.
- **Artifacts:** `scripts/render_cg_insert.py` and
  `reports/refball-tone-probe-20260815/` (README, asset A/B, ref-ball composite,
  `ground_occlusion.json`, `diag_ground_occlusion.py`, render_meta.json) —
  committed. `/tmp/lm_ground` is deliberate reproducible scratch.
- **State:** Finding, not a fix. Every CG insert this pipeline has produced is
  over-lit from below by light passing through the ground it stands on. Tone
  path confirmed good by the chrome ball. Flat-plane world, missing curb,
  untextured asset, and the camera-curve gap all still open. Intake stays 1/5.
- **Next owner + concrete artifact:** Gonzo, **not started, awaiting DiMo's nod**
  because it changes the fixture contract: replace `is_shadow_catcher` with a
  real matte ground proxy and extract the shadow as a difference pass (ground
  rendered with and without the object, ratio as the shadow matte). Pairs with
  the proxy wall/occluder geometry queued from
  `reports/ground-contact-20260814/`.
- **Failure mode recorded:** a saturated placeholder material stood in for a
  real asset through weeks of lighting work. Neutral reference geometry is the
  instrument that makes lighting errors measurable and belongs in the loop from
  the first render, not at the end. The bug was visible in every composite and
  unreadable through the salmon.

## 2026-08-15 01:10 PDT — Gonzo tonemap: one view transform end to end

- **What was done:** DiMo: "make sure the images are tonemapped correctly."
  Evidence: the plate was tonemapped by OpenCV Reinhard while the CG was
  rendered through Blender's default AgX, which `render_cg_insert.py` never set
  and silently inherited — a source-level tone mismatch no relight stage could
  close. New `scripts/tonemap_pano.py` tonemaps the panorama through Blender's
  own OCIO view transform (`Image.save_render`, HDR read as Linear Rec.709), so
  plate and render share one operator by construction. `render_cg_insert.py`
  now pins colour management (`--view-transform/--look/--exposure/--gamma`,
  default AgX) and re-applies it in `render()` before every write, since scene
  resets restore factory settings; an unavailable transform is a hard error.
  `build_intake_tranche.py` drives both ends from one `VIEW_TRANSFORM` constant
  and the fixture field is now `blender-ocio(AgX,...)`. Added an un-normalised
  raw term to the projection scores so tone can no longer hide behind contrast
  normalisation. Measured plate vs background render, linear, raw pixels:
  raw MSE 0.007669 -> 0.000050 (153x), mean delta +0.0239 -> -0.0010, std ratio
  0.562 -> 0.993, normalised identity correlation 0.9855 -> 0.9995. Plate
  p1..p99 43..193 -> 14..233. Ground contact re-verified unchanged
  (`bbox_min_z` 0.0, 72 stray alpha pruned, 63 869 kept).
- **Artifacts:** `scripts/tonemap_pano.py`, `scripts/render_cg_insert.py`,
  `scripts/build_intake_tranche.py`, `reports/tonemap-match-20260815/`
  (README, plate A/B, composite A/B, sheet, render_meta.json, tonemap_meta.json)
  — committed. `/tmp/lm_ground` is deliberate reproducible scratch.
- **State:** Partial. Tone path correct and measured. Not fixed and stated in
  the report: the CG object never changed (it was always AgX; the plate was the
  wrong one), so it still does not belong to the scene tonally — that is the
  relight stage. This matches a tonemapped panorama to a render, not a camera
  to a render, so it does not carry over to the >=2 `camera_original` cases
  Layer-2 requires. Flat-plane world, missing curb, and untextured Suzanne all
  still open. Intake stays 1/5 pending a tranche rebuild.
- **Next owner + concrete artifact:** Gonzo. Rebuild the four-case tranche via
  `scripts/build_intake_tranche.py` on the corrected chain, then proxy occluder
  geometry, then a textured asset.
- **Failure mode recorded:** the render script inherited a default view
  transform while the plate path set an explicit different one. An inherited
  default on one side of a comparison is an unstated assumption. Both sides of a
  pixel comparison must name their transform, and the metric needs an
  un-normalised term or a tone mismatch hides behind contrast normalisation.

## 2026-08-14 18:05 PDT — Gonzo ground contact + shadow containment

- **What was done:** DiMo's directive in #latent-merge: the CG must sit on the
  surface visible in the plate and its shadows must live in that world.
  Evidence: rewrote insertion in `scripts/render_cg_insert.py`. Contact point
  is now a plate pixel (`--place-uv`) unprojected onto the solved ground plane;
  a pixel at or above the horizon is a hard error. `rest_on_ground` scales to a
  metre height and snaps the world bbox floor to the plane (`bbox_min_z` 0.0 on
  this run, recorded in `render_meta.json`). `--verify-ground` renders the plane
  as an emissive 1 m grid over the plate so the plane is checked by eye, not
  assumed. `prune_stray_alpha` keeps only alpha connected to the object, so
  shadow-catcher speckle cannot touch plate pixels elsewhere: 72 stray pruned,
  63 869 kept, composite modifies 3.08% of the plate. Background alignment
  unaffected (identity correlation 0.986 vs 0.064/0.193/0.039 mirrors).
- **Artifacts:** `scripts/render_cg_insert.py` and
  `reports/ground-contact-20260814/` (README, contact sheet, grid overlay,
  composite, render_meta.json) — committed. `/tmp/lm_ground` is deliberate
  reproducible scratch, not committed.
- **State:** Partial. Grounding and shadow containment done and looked at.
  Still wrong and stated in the report: the world is one infinite flat plane
  (grid runs through the parked car and up the shopfronts, nothing occludes,
  shadows cannot climb a wall), no curb model, the asset is still an untextured
  Suzanne balancing on her chin so LOCKED L4 has nothing to test, and the
  object's shading does not belong to the scene yet. Intake stays 1/5.
- **Next owner + concrete artifact:** Gonzo. Proxy scene geometry (ground +
  wall planes + coarse occluder for the parked car) from the same camera solve,
  verified with `--verify-ground`; then a textured asset and a tranche rebuild
  via `scripts/build_intake_tranche.py`.
- **Failure mode recorded:** placement was expressed in camera-relative metres,
  a space nobody can check against the photograph, which let "floating Suzanne"
  survive several sessions. Insertion parameters must live in the space where
  the error is visible (image pixels), and every geometric assumption needs a
  render laid over the plate.

## 2026-08-14 09:08 PDT — Gonzo projection convention fix

- **What was done:** Evidence: replaced the unreliable azimuth search with the
  actual basis transform: Blender azimuth is `270 - plate yaw`, and Blender
  camera X rotation is `90 - pitch` because `pano_to_plate.py` negative pitch
  looks up. Rendered background checks for all four real panorama crops and
  inspected the pixels. Geometry, framing, horizon and orientation reproduce
  on all four; identity correlation is 0.955 harsh sun, 0.987 indoor, 0.986
  alley, and 0.831 Venice. Venice's buildings/tree/fence/road register but its
  score remains lower because the plate's Reinhard tonemap is severely washed
  out. A full Venice CG run also completed with the deterministic mapping.
- **Artifacts:** `scripts/render_cg_insert.py`,
  `reports/projection-convention-fix-20260814/plate_vs_blender_fixed.jpg`,
  `scores.json`, and `README.md` (committed). `/tmp/lm_projection_diag` and
  `/tmp/lm_projection_fixed_run` are deliberate reproducible scratch, not
  committed.
- **State:** Projection defect done. This is plumbing evidence, not a quality
  result; intake stays 1/5. Pixel flaws still present: plate/render tone curves
  disagree, the plates are washed out, the indoor panorama has a visible seam,
  and untextured floating Suzanne still provides no L4 identity test.
- **Next owner + concrete artifact:** Gonzo owns tonemap replacement next. Use
  `reports/projection-convention-fix-20260814/plate_vs_blender_fixed.jpg` as
  the geometry-locked reference and change only tone before rechecking pixels.
- **Failure mode recorded:** image-search optimisation hid a known coordinate
  transform and chose wrong views when tone dominated grayscale MSE. Projection
  conventions must be encoded algebraically and verified with identity/mirror
  pixel scores.

## 2026-08-13 15:20 PDT — Gonzo (DiMo: "make the decisions, move faster")

- **What was done:** Evidence: ruled issue #3 myself (YES-with-caveat: a
  gnomonic crop of a CC0 photo-panorama is photographic under L1 because the
  plate pixels are untouched camera pixels; the real weakness is capture
  geometry, so plates carry `capture_class: panorama_crop` and Layer-2 now
  additionally requires >=2 `camera_original` cases). Then built the #2-#5
  tranche rather than waiting: new `scripts/build_intake_tranche.py`, four
  CC0 Poly Haven panoramas spanning harsh sun / low warm sun / indoor soft /
  overcast shade. Validator returned ok:true on 4/4 at 1920x1080. Inspected
  the pixels and **rejected all four**. Three defects found, documented in
  `reports/intake-tranche-attempt-20260813/README.md`: (1) matched-HDRI
  azimuth alignment does not reproduce — a full 360 deg 5 deg sweep on the
  venice case shows no minimum anywhere (best MSE 1.287 = r 0.36; the June
  case hit 0.52 = r 0.74), and higher search resolution plus a gradient
  descriptor both failed, so it is a projection-convention mismatch, not
  optimiser tuning; (2) my Reinhard tonemap yields washed-out non-photographic
  plates; (3) the CG insert is an untextured floating Suzanne, so LOCKED L4
  has nothing to preserve. Also scripted the HDR->LDR tonemap step, which the
  2026-06-27 "proven end-to-end" chain performed by hand.
- **Artifacts:** `scripts/build_intake_tranche.py` (committed);
  `reports/intake-tranche-attempt-20260813/` with README, the
  plate/bg-render/composite contact sheet showing the misalignment, and
  `az_error_surface_venice.json` (committed). Built fixtures left in
  `/tmp/lm_out` as deliberate scratch and **not** promoted into `fixtures/`.
  Removed three zero-byte stray files from the project root that shadowed the
  real tools in `scripts/`.
- **State:** Intake remains 1/5. Issue #3 is no longer the blocker and the
  four-minute build proves it never should have been one for twelve days. The
  fixture chain is **not** "proven end to end" as `NEXT_STEPS.md` claims — it
  was proven on exactly one panorama and does not generalise. GPU is a
  separate, genuinely physical block: `lspci` shows no NVIDIA device on the
  bus at all.
- **Next owner + concrete artifact:** Gonzo owns all three defects. Order:
  fix the projection convention (diff the Blender background at the plate's
  exact yaw against the plate and its two mirrors to identify the flip), then
  the Blender-matched tone curve, then a textured asset on a solved ground
  plane, then rebuild. DiMo owns exactly one thing: reseating the eGPU so the
  relight backend can run.
- **Failure mode recorded:** a validator PASS was again about to be mistaken
  for progress. 4/4 ok:true on fixtures whose HDRI match is fabricated is the
  same class of miss as the June fake-plate spiral. The check that caught it
  was looking at the image, not reading the JSON.

## 2026-08-13 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, photographic fixture/report inputs newer than
  the previous pulse, local/remote HEAD, and NVIDIA visibility. No activation
  criterion changed: issue #3's YES/NO ruling remains unchecked, no new input
  or PR arrived, the newest Action remains the successful 2026-07-20 run,
  both HEADs are `223b226`, and NVIDIA remains unavailable. Inference: the
  evidence-triggered gate leaves no safe technical work active, so unchanged
  validators were not rerun and no reminder or channel update was produced.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review are that checkbox;
  the next Gonzo run activates only on that ruling, new photographic input,
  usable CUDA hardware, or verified project drift.

## 2026-08-12 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, post-morning fixture/report inputs,
  local/remote HEAD, and NVIDIA visibility. Nothing gate-relevant changed
  after the morning pulse: issue #3's YES/NO ruling remains unchecked, no new
  input or PR arrived, the newest Action remains the successful 2026-07-20
  run, both HEADs are `da26411`, and NVIDIA remains unavailable. Inference:
  the morning commitment is already correctly scoped to evidence, so this
  afternoon action closes the scheduled audit without another reminder,
  validator rerun, or date-driven technical promise.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run activates only on that ruling, new photographic
  input, usable CUDA hardware, or verified project drift, and should target
  the resulting evidence.

## 2026-08-12 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, photographic fixture/report inputs newer than
  the previous pulse, and local/remote HEAD. No activation criterion changed:
  issue #3's YES/NO ruling remains unchecked, no new input or PR arrived, the
  newest Action remains the successful 2026-07-20 run, and both HEADs are
  `8879454`. Inference: the evidence-triggered gate leaves no safe technical
  work active, so unchanged validators and CUDA checks were not rerun and no
  reminder or channel update was produced.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review are that checkbox;
  the next Gonzo run activates only on that ruling, new photographic input,
  usable CUDA hardware, or verified project drift.

## 2026-08-11 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, post-morning fixture/report inputs,
  local/remote HEAD, and NVIDIA visibility. Nothing gate-relevant changed
  after the morning pulse: issue #3's YES/NO ruling remains unchecked, no new
  input or PR arrived, the newest Action remains the successful 2026-07-20
  run, both HEADs are `95f7d20`, and NVIDIA remains unavailable. Inference:
  the morning commitment is already correctly scoped to evidence, so this
  afternoon action closes the scheduled audit without another reminder,
  validator rerun, or date-driven technical promise.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run activates only on that ruling, new photographic
  input, usable CUDA hardware, or verified project drift, and should target
  the resulting evidence.

## 2026-08-11 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, photographic fixture/report inputs newer than
  the previous pulse, local/remote HEAD, and NVIDIA visibility. No activation
  criterion changed: issue #3's YES/NO ruling remains unchecked, no new input
  or PR arrived, the newest Action remains the successful 2026-07-20 run,
  both HEADs are `5e44a2f`, and NVIDIA is unavailable. Inference: the
  evidence-triggered gate leaves no safe technical work active, so unchanged
  validators were not rerun and no reminder or channel update was produced.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review are that checkbox;
  the next Gonzo run activates only on that ruling, new photographic input,
  usable CUDA hardware, or verified project drift.

## 2026-08-10 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, post-morning fixture/report inputs, and
  local/remote HEAD. Nothing changed after the morning pulse: issue #3's
  YES/NO ruling remains unchecked, no new input or PR arrived, the latest
  Action is still the successful 2026-07-20 run, and both HEADs are `8c4a345`.
  Inference: the evidence-triggered commitment remains correctly scoped, so
  this afternoon audit closes without another reminder, validator rerun, or
  date-driven technical promise.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run activates only on that ruling, new photographic
  input, usable CUDA hardware, or verified project drift, and should target
  the resulting evidence.

## 2026-08-10 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, fixture/report inputs, local/remote HEAD, and
  NVIDIA visibility. No ruling, input, repository, CI, gate, or hardware delta
  arrived since the previous pulse; issue #3's YES/NO boxes remain unchecked,
  no PR is open, the newest Action remains the successful 2026-07-20 run, and
  NVIDIA is still unavailable. Inference: the evidence-triggered gate leaves
  no safe technical work active, so unchanged validators were not rerun and no
  reminder or channel update was produced.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review are that checkbox;
  the next Gonzo run activates only on that ruling, new photographic input,
  usable CUDA hardware, or verified project drift.

## 2026-08-09 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, Actions, post-morning fixture/report inputs, local/remote
  HEAD, and NVIDIA visibility. No ruling, input, repository, CI, gate, or
  hardware delta arrived; issue #3's YES/NO boxes remain unchecked, no files
  landed in the input surfaces after the morning pulse, and NVIDIA remains
  unavailable. Inference: the morning commitment is already correctly scoped
  to evidence, so this afternoon action closes the scheduled audit without
  another reminder, validator rerun, or date-driven commitment.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as an evidence-triggered no-op. The intake remains 1/5 and
  dormant; no `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run activates only on that ruling, new photographic
  input, usable CUDA hardware, or verified project drift, and should target
  the resulting concrete evidence.

## 2026-08-09 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, Actions, local/remote HEAD, and project inputs since the last
  pulse. No ruling, input, repository, CI, or gate delta arrived; issue #3's
  YES/NO boxes remain unchecked and both HEADs are `c7df430`. Inference: the
  evidence-triggered gate correctly leaves no safe technical work active, so
  unchanged validators and CUDA checks were not rerun and no reminder was
  posted.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as a verified no-op. The intake remains 1/5 and dormant; no
  `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review are that checkbox;
  the next Gonzo run activates only on that ruling, new photographic input,
  usable CUDA hardware, or verified project drift.

## 2026-08-08 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, Actions, the local branch, and post-morning project inputs.
  Local and remote HEAD remain identical; no ruling, input, PR, CI run, or
  gate-relevant repository delta arrived. Inference: the morning commitment is
  already correctly scoped to evidence, so this afternoon action closes the
  scheduled audit without another reminder, validator rerun, or gate-doc edit.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Done as an evidence-triggered no-op. The intake gate remains 1/5
  and dormant pending a qualifying delta; no `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run activates only on that ruling, new photographic
  input, usable CUDA hardware, or verified project drift, and should target the
  resulting concrete evidence rather than another scheduled audit.

## 2026-08-08 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, Actions, post-pulse photographic inputs, and NVIDIA device
  visibility. No activation criterion changed since the 2026-08-07 pulse:
  issue #3 remains unchecked, no input or repository work arrived, and this
  runtime still cannot communicate with an NVIDIA driver. Inference: today's
  bounded action is to close the scheduled audit without rerunning unchanged
  validators, sending another reminder, or manufacturing project churn.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; existing dirty untracked project
  files were not touched.
- **State:** Blocked at the parked intake decision; no new technical result is
  unverified, and no `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review are that checkbox;
  the next Gonzo run activates only on a ruling, new photographic input,
  usable CUDA hardware, or verified project drift.

## 2026-08-07 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, Actions, the local branch, and NVIDIA device visibility. None
  of the evidence-triggered activation criteria changed since the previous
  pulse: issue #3 remains unchecked, no photographic input arrived, no PR or
  CI run appeared, local and remote HEAD are identical, and no NVIDIA device is
  visible. Inference: the correct bounded action was to preserve the parked
  gate rather than rerun unchanged checks or create another reminder.
- **Artifacts:** This `TASKLOG.md` audit entry, committed and pushed. No
  generated or scratch artifact remains; dirty untracked project files were
  not touched.
- **State:** Blocked at the existing intake decision; no technical result is
  newly unverified and no `#latent-merge` post is warranted.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review remain that checkbox;
  the next Gonzo run activates only on a ruling, new photographic input,
  visible CUDA hardware, or verified project drift.

## 2026-08-06 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, Actions, and local NVIDIA visibility; no ruling, input, PR,
  CI, hardware, or branch delta exists since the morning pulse. Re-scoped the
  live board's stale date-driven "today" commitment into an evidence-triggered
  activation gate. Inference: future pulses now have an explicit no-date target
  and should not create bookkeeping solely because another scheduled run fired.
- **Artifacts:** `NEXT_STEPS.md` and this `TASKLOG.md` entry, committed and
  pushed. No generated or scratch artifact remains; dirty untracked project
  files were not touched.
- **State:** Done. The intake gate remains 1/5 and intentionally dormant pending
  new evidence; unchanged validators were not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run should use the activation criteria in
  `NEXT_STEPS.md` and remain silent unless one is satisfied.

## 2026-08-06 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, Actions, and local NVIDIA visibility. Nothing changed
  after yesterday's parked-reminder commit: the intake ruling is unchecked,
  no PR is open, no new Actions run exists, and this runtime still cannot use
  NVIDIA hardware. Inference: the evidence-trigger rule correctly leaves no
  safe technical action in Gonzo's lane today, so no reminder, validation
  rerun, or cosmetic gate edit was made.
- **Artifacts:** This `TASKLOG.md` audit entry only, committed and pushed. No
  generated or scratch artifact remains; dirty untracked project files were
  not touched.
- **State:** Blocked at the existing intake decision; no technical result is
  newly unverified.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in assigned
  GitHub issue #3. Today's concrete gate and most valuable review are that
  checkbox; after YES, Gonzo uses
  `reports/cg-insert-matched-hdri-20260627/README.md` to build the five-case
  tranche. The next Gonzo run should act only on a ruling, new photographic
  inputs, visible CUDA hardware, or verified project drift.

## 2026-08-05 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, and Actions; no ruling, input, PR, CI, or hardware delta exists
  since morning. Posted one concise assignee notification on issue #3 requesting
  the existing YES/NO ruling, then explicitly parked further reminder and
  documentation churn until project evidence changes. Inference: the blocker
  has a fresh direct notification surface without creating another recurring
  pseudo-commitment for workers.
- **Artifacts:** GitHub issue #3 comment, `NEXT_STEPS.md`, and this
  `TASKLOG.md` entry; documentation committed and pushed. No generated or
  scratch artifact remains; dirty untracked project files were not touched.
- **State:** Done. Gate remains 1/5 pending the ruling; unchanged technical
  checks were intentionally not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in assigned
  GitHub issue #3. The next Gonzo run should act only on that ruling, new
  photographic inputs, visible CUDA hardware, or verified project drift; issue
  #6 remains parked until photographic Layer-2 acceptance.

## 2026-08-05 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, open PRs, and Actions; no ruling, input, PR, CI, or hardware delta
  exists since yesterday. Found and removed a formal-gate contradiction: the
  locked-set definition still required all fixtures to be "provided by DiMo"
  while issue #3's YES path permits approved CC0 photographic panorama crops.
  `PHASE2_GATE.md` now makes sourcing explicitly conditional on issue #3's
  ruling. Inference: a YES decision can now activate the intake build without
  conflicting with the formal gate definition.
- **Artifacts:** `PHASE2_GATE.md`, `NEXT_STEPS.md`, and this `TASKLOG.md` entry;
  documentation committed and pushed. No generated or scratch artifact
  remains; dirty untracked project files were not touched.
- **State:** Done. Gate remains 1/5 pending the YES/NO ruling; unchanged
  technical checks were intentionally not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in assigned
  GitHub issue #3. Today's concrete gate and most valuable review are that
  ruling; YES activates the documented CC0 matched-HDRI path, while NO requires
  DiMo-supplied photographic plates/footage plus matched HDRI.

## 2026-08-04 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, and Actions; no ruling, input, PR, CI, or hardware delta
  exists since morning. Re-scoped the stale downstream release commitment by
  removing the `gonzo` and `dimo` ownership labels from blocked issue #6 while
  retaining its `blocked`, `release`, and `docs` classifications. Inference:
  release packaging is now visibly parked instead of presenting inactive work
  as a current commitment.
- **Artifacts:** GitHub issue #6 labels, `NEXT_STEPS.md`, and this `TASKLOG.md`
  entry; documentation committed and pushed. No generated or scratch artifact
  remains; dirty untracked project files were not touched.
- **State:** Done. Gate remains 1/5 pending the YES/NO ruling in issue #3;
  unchanged technical checks were intentionally not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in assigned
  GitHub issue #3. The next Gonzo run should act on that ruling, new
  photographic inputs, visible CUDA hardware, or verified project drift;
  issue #6 should receive an owner only after photographic Layer-2 acceptance.

## 2026-08-04 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, and the committed matched-HDRI proof; no ruling, source,
  input, PR, or CI delta exists since yesterday. Embedded the existing
  committed four-panel contact sheet directly in issue #3 and converted its
  reproduction pointer to a clickable repository link. Inference: DiMo can now
  make the binary intake ruling from the assigned issue without locating local
  or untracked report files.
- **Artifacts:** GitHub issue #3 body,
  `reports/cg-insert-matched-hdri-20260627/cg_insert_contact_sheet.png`,
  `NEXT_STEPS.md`, and this `TASKLOG.md` entry. The visual was already committed;
  documentation is committed and pushed. Dirty untracked project files were
  not touched; the temporary issue-body file is explicit disposable scratch.
- **State:** Done. Gate remains 1/5 pending the YES/NO ruling; unchanged
  technical checks were intentionally not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3 after reviewing its embedded contact sheet. Today's concrete gate
  and most valuable review are that ruling; YES activates the five-case build,
  while NO requires DiMo-supplied plates/footage plus matched HDRI.

## 2026-08-03 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, and Actions; no intake ruling, source, input, PR, or CI delta
  exists since morning. Re-scoped the stale release commitment by adding the
  `blocked` label to issue #6, matching its documented dependency on accepted
  photographic evidence from issue #3. Inference: the GitHub issue list no
  longer presents downstream packaging as runnable work.
- **Artifacts:** GitHub issue #6 labels, `NEXT_STEPS.md`, and this `TASKLOG.md`
  entry; project documentation committed and pushed. No generated or scratch
  artifact remains; dirty untracked project files were not touched.
- **State:** Done. Gate remains 1/5 pending the YES/NO ruling in issue #3;
  unchanged technical checks were intentionally not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run should act on that ruling, new photographic
  inputs, visible CUDA hardware, or verified project drift; issue #6 stays
  blocked until photographic Layer-2 acceptance exists.

## 2026-08-03 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main` and inspected issue #3,
  issue #6, PRs, and Actions; no source, input, ruling, or CI delta exists
  since yesterday afternoon. Retitled issue #3 from the broad fixture-build
  wording to `Decision required: accept CC0 photo-panorama plates for eval
  set`, exposing the actual binary unblocker in GitHub's issue list.
  Inference: the assigned decision now requires no issue-body archaeology.
- **Artifacts:** GitHub issue #3 title, `NEXT_STEPS.md`, and this `TASKLOG.md`
  entry; project documentation committed and pushed. No generated or scratch
  artifact remains; dirty untracked project files were not touched.
- **State:** Done. The gate remains 1/5 pending a YES/NO ruling; unchanged
  technical checks were intentionally not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. Today's concrete gate and most valuable review are that single
  ruling; YES activates the proven matched-HDRI fixture chain, while NO makes
  DiMo the source for plates/footage plus matched HDRI.

## 2026-08-02 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main` and inspected issues #3
  and #6, PRs, and Actions; no source, input, decision, or CI delta exists
  since morning. Assigned issue #3 to `neodimo` (DiMo), replacing an
  unassigned blocker with explicit GitHub ownership. Inference: the live issue
  surface now matches the project board's named next owner.
- **Artifacts:** GitHub issue #3 assignment, `NEXT_STEPS.md`, and this
  `TASKLOG.md` entry; project documentation committed and pushed. No generated
  or scratch artifact remains; dirty untracked project files were not touched.
- **State:** Done. Gate remains 1/5 and issue #3 still awaits a YES/NO ruling;
  unchanged technical checks were intentionally not rerun.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in assigned
  GitHub issue #3. The next Gonzo run should act only on that ruling, new
  photographic inputs, visible CUDA hardware, or verified project drift.

## 2026-08-02 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main`, inspected issues #3 and
  #6, open PRs, and Actions state; no source or decision delta exists since
  yesterday. Corrected issue #3's stale `phase-1` classification to `phase-2`
  and added `blocked`, while retaining `dimo` and `fixture`. Inference: the
  repository's issue surface now exposes the actual current gate and owner
  without requiring readers to reconstruct it from comments.
- **Artifacts:** GitHub issue #3 labels and this committed task-log entry. No
  generated or scratch artifact remains; dirty untracked project files were
  not touched.
- **State:** Done. Gate remains 1/5; no technical validation was rerun because
  source and fixture inputs are unchanged.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The most valuable review today is that single ruling. On YES,
  Gonzo uses `reports/cg-insert-matched-hdri-20260627/README.md` to build the
  five-case tranche; on NO, DiMo supplies plates/footage and matched HDRI.

## 2026-08-01 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main`, inspected issues #3 and
  #6 and open PRs, and found no technical or decision delta since morning.
  Re-scoped stale issue #3 from an open-ended sourcing handoff to two explicit
  YES/NO checkboxes, with the proven YES-path command chain and the NO-path
  input obligation embedded in the issue body. Inference: the intake gate now
  has one unambiguous response surface and the next worker pulse can trigger on
  a checked decision rather than repeat unchanged validation.
- **Artifacts:** GitHub issue #3 body and this committed task-log entry. No
  generated or scratch artifact remains. The first issue edit was damaged by
  shell interpolation; verification caught it immediately and the body was
  restored from a literal file, then re-read through the GitHub API.
- **State:** Done. Gate remains 1/5 and no technical check was rerun because
  source and inputs are unchanged.
- **Next owner + concrete artifact:** DiMo owns checking YES or NO in GitHub
  issue #3. The next Gonzo run should inspect those checkboxes first; on YES,
  use `reports/cg-insert-matched-hdri-20260627/README.md`; on NO, wait for the
  supplied plates/footage and matched HDRI.

## 2026-08-01 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main`, queried GitHub issues #3
  and #6 and open PRs, and confirmed no external delta since the 2026-07-31
  pulse. Replaced the duplicated pulse-by-pulse archive in `NEXT_STEPS.md` with
  a concise live dependency/ownership board; historical completion evidence
  remains here in the append-only ledger. Inference: the shorter board removes
  stale chronology from the execution path without changing the gate.
- **Artifacts:** `NEXT_STEPS.md` and this `TASKLOG.md` entry; committed project
  documentation. No generated or scratch artifact.
- **State:** Done. Issue #3 remains the intake decision and issue #6 remains
  downstream of accepted photographic Layer-2 evidence; no technical check was
  rerun because source and inputs are unchanged.
- **Next owner + concrete artifact:** DiMo owns the YES/NO ruling in GitHub
  issue #3. After YES, Gonzo uses
  `reports/cg-insert-matched-hdri-20260627/README.md` to build the five-case
  tranche; after NO, DiMo supplies plates/footage plus matched HDRI.

## 2026-07-31 16:00 PDT — Gonzo afternoon worker

- **What was done:** Evidence: fetched `origin/main`, queried GitHub issues #3
  and #6 plus PR state, and confirmed the only repo delta since morning is the
  durable-ledger commit `87fa612`; issue #3 is unchanged since 2026-06-30,
  issue #6 since 2026-06-23, and no PR is active. Refreshed the formal gate's
  stale verification marker to 2026-07-31. Inference: there is no new technical
  or gate-state delta, so rerunning unchanged intake/CUDA checks would add no
  evidence.
- **Artifacts:** `PHASE2_GATE.md`, `NEXT_STEPS.md`, and this `TASKLOG.md` entry;
  committed project documentation. No generated or scratch artifact.
- **State:** Done. The formal status now matches today's verified repo/GitHub
  state; intake remains externally blocked at 1/5.
- **Next owner + concrete artifact:** DiMo owns the YES/NO ruling in GitHub issue
  #3. The next Gonzo run should inspect that issue first and use
  `reports/cg-insert-matched-hdri-20260627/README.md` only after YES or supplied
  plates/HDRI; otherwise it should stay silent unless new drift is verified.

## 2026-07-31 08:00 PDT — Gonzo morning worker

- **What was done:** Evidence: fetched `origin/main`, queried GitHub issue #3 and
  open PRs, and confirmed `HEAD == origin/main == 19d48df`, issue #3 remains
  open with 8 comments and `updatedAt: 2026-06-30T23:01:06Z`, and no PR is
  open. Closed the missing durable completion-ledger gap by adding this file.
  Inference: no technical or gate delta has occurred since the 2026-07-30
  afternoon pulse.
- **Artifacts:** `TASKLOG.md` and the refreshed live snapshot date in
  `NEXT_STEPS.md`; both committed project files. No generated visual or runtime
  artifact was produced.
- **State:** Done. Gate behavior was not re-run because source and inputs are
  unchanged; the last recorded suite result remains 21/21. The photographic
  intake gate remains externally blocked at 1/5 pending issue #3.
- **Next owner + concrete artifact:** Omid/DiMo should answer the binary ruling
  in GitHub issue #3. On YES, Gonzo uses the chain documented in
  `reports/cg-insert-matched-hdri-20260627/README.md`; on NO, DiMo supplies real
  plates/footage plus matched HDRI.
