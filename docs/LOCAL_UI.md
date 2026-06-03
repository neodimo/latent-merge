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

On Windows, use the same command from PowerShell with your Python launcher:

```powershell
py -m pip install --target .deps -r requirements.txt
$env:PYTHONPATH=".deps;."
py ui/local_app.py
```

## GitHub Executables

The `Build UI executables` GitHub Actions workflow packages the local UI as:

- `latent-merge-ui-linux`
- `latent-merge-ui-windows`

Run it from the GitHub Actions tab with `workflow_dispatch`, or let it run on relevant pushes and PRs. Download the artifact for your OS, start the executable from a writable project folder, then open the printed local URL. Outputs are written under `runs/ui_jobs/` beside the folder where the executable is launched.

## Current Support

- A side: PNG with embedded alpha.
- B side: PNG or JPG.
- Optional matte override: PNG or JPG. If omitted, the A-side PNG alpha is used.
- Multiple uploaded files are accepted so the UI shape matches frame-sequence workflow. The current runner processes the first sorted frame only and records uploaded frame counts in `ui_job.json`.
- GPU dropdown is populated from `nvidia-smi` when available and is wired through `CUDA_VISIBLE_DEVICES`.
- PCT controls:
  - Adjustment Strength: `0` keeps original CG, `1` uses the model result, and higher values exaggerate the correction.
  - Delta Preview Gain: brightens diagnostic delta passes only; it does not alter the adjusted foreground or final comp.
  - Correction Softness: feathers where the model correction applies, without changing the saved alpha.
  - Correction Choke: negative values expand correction influence outward; positive values pull it inward from edges.
- Outputs are written under `runs/ui_jobs/<job-id>/`.

## EXR / ACEScg

The UI accepts EXR file selection as part of the contract, but execution is currently blocked with a clear error. The next implementation step is adding an OpenImageIO/OpenColorIO conversion bridge:

```text
EXR ACEScg -> model working gamut/proxy -> adjusted foreground -> display/output transform
```

Until that bridge lands, use sRGB PNG/JPG proxies for interactive tests.
