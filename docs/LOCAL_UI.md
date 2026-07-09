# Local UI

Run from the repo root:

```bash
python3 -m pip install --target .deps -r requirements.txt
PYTHONPATH=".deps:." python3 ui/local_app.py
```

Open:

```text
http://127.0.0.1:7865
```

That URL is local to the machine running the app. If Gonzo runs the server on a
remote box, DiMo cannot open Gonzo's `127.0.0.1`; run the app on DiMo's machine
from a checkout instead. A new packaged release is intentionally deferred until
the photographic Layer-2 gate is accepted.

On Windows, use the same command from PowerShell with your Python launcher:

```powershell
py -m pip install --target .deps -r requirements.txt
$env:PYTHONPATH=".deps;."
py ui/local_app.py
```

## GitHub Executables

The `Build UI executables` GitHub Actions workflow can package the local UI as:

- `latent-merge-ui-linux`
- `latent-merge-ui-windows`

Current release rule: do not publish or treat a packaged UI executable as the
active project checkpoint until issue #6 is satisfied by accepted photographic
Layer-2 evidence. Existing or workflow-generated binaries are operational
smoke artifacts only.

For local operational testing, run the workflow from the GitHub Actions tab
with `workflow_dispatch`, download the artifact for your OS, start the
executable from a writable project folder, then open the printed local URL.
Outputs are written under `runs/ui_jobs/` beside the folder where the executable
is launched.

## Current Support

- A side: PNG with embedded alpha.
- B side: PNG or JPG.
- Optional matte override: PNG or JPG. If omitted, the A-side PNG alpha is used.
- Multiple uploaded files are accepted so the UI shape matches frame-sequence workflow. The current runner processes the first sorted frame only and records uploaded frame counts in `ui_job.json`.
- GPU dropdown is populated from `nvidia-smi` when available and is wired through `CUDA_VISIBLE_DEVICES`.
- IC Flux v2 is an external GPU backend. The UI executable bundles the control surface and runner script, but it does not bundle the CUDA Python stack or model weights. Use the IC Flux panel to:
  - download or locate IC-Light/FLUX model weights
  - create or repair an app-managed Python runtime under `runtimes/ic-flux/<runtime-version>/venv`
  - locate an existing compatible Python runtime
  - inspect setup progress and validation logs

The managed setup installs CUDA torch from the configured PyTorch index plus the IC Flux Python packages, validates CUDA visibility, and records the selected interpreter in `ic_flux_runtime.json`. Manual setup is still supported with `LATENT_MERGE_IC_FLUX_PYTHON` or `LATENT_MERGE_PYTHON`:

```bash
python3 -m venv .ic-flux-venv
.ic-flux-venv/bin/python -m pip install -U pip
.ic-flux-venv/bin/python -m pip install numpy Pillow diffusers transformers accelerate huggingface_hub safetensors
.ic-flux-venv/bin/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
LATENT_MERGE_IC_FLUX_PYTHON="$PWD/.ic-flux-venv/bin/python" ./bin/latent-merge-ui
```

  The UI checks this runtime before enabling IC Flux runs and reports missing packages or missing CUDA before files are uploaded into a job.
- PCT controls:
  - Adjustment Strength: `0` keeps original CG, `1` uses the model result, and higher values exaggerate the correction.
  - Delta Preview Gain: brightens diagnostic delta passes only; it does not alter the adjusted foreground or final comp.
  - Correction Softness: feathers where the model correction applies, without changing the saved alpha.
  - Correction Choke: negative values expand correction influence outward; positive values pull it inward from edges.
- Latent Delta backend:
  - Uses the same upload/run/output surface as the existing UI.
  - Produces proposal/delta/shadow inspection artifacts while preserving the current trusted final comp contract.
  - Shadow preview is not baked into `final_comp` until the Layer-1 gate supports an explicit interaction mask.
- Outputs are written under `runs/ui_jobs/<job-id>/`.

## EXR / ACEScg

The UI accepts EXR file selection as part of the contract, but execution is currently blocked with a clear error. The next implementation step is adding an OpenImageIO/OpenColorIO conversion bridge:

```text
EXR ACEScg -> model working gamut/proxy -> adjusted foreground -> display/output transform
```

Until that bridge lands, use sRGB PNG/JPG proxies for interactive tests.
