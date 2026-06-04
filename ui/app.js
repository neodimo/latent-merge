const fields = {
  cg: document.getElementById("cgInput"),
  plate: document.getElementById("plateInput"),
  alpha: document.getElementById("alphaInput"),
};

const lists = {
  cg: document.getElementById("cgList"),
  plate: document.getElementById("plateList"),
  alpha: document.getElementById("alphaList"),
};

const runButton = document.getElementById("runButton");
const icFluxInlineDownloadButton = document.getElementById("icFluxInlineDownloadButton");
const updateButton = document.getElementById("updateButton");
const updateStatus = document.getElementById("updateStatus");
const statusEl = document.getElementById("status");
const gpuSelect = document.getElementById("gpuSelect");
const backendSelect = document.getElementById("backendSelect");
const controlTitle = document.getElementById("controlTitle");
const controlDescription = document.getElementById("controlDescription");
const backendHint = document.getElementById("backendHint");
const modelPill = document.getElementById("modelPill");
const vitControls = document.getElementById("vitControls");
const icFluxControls = document.getElementById("icFluxControls");
const icFluxModelStatus = document.getElementById("icFluxModelStatus");
const icFluxDownloadButton = document.getElementById("icFluxDownloadButton");
const icFluxDownloadProgress = document.getElementById("icFluxDownloadProgress");
const icFluxDownloadDetail = document.getElementById("icFluxDownloadDetail");
const controls = {
  strength: document.getElementById("strengthInput"),
  deltaGain: document.getElementById("deltaGainInput"),
  softness: document.getElementById("softnessInput"),
  choke: document.getElementById("chokeInput"),
  vitContext: document.getElementById("vitContextInput"),
  vitContrast: document.getElementById("vitContrastInput"),
  vitWarmth: document.getElementById("vitWarmthInput"),
  vitSaturation: document.getElementById("vitSaturationInput"),
  vitIdentity: document.getElementById("vitIdentityInput"),
  icFluxSeed: document.getElementById("icFluxSeedInput"),
  icFluxSteps: document.getElementById("icFluxStepsInput"),
  icFluxCfg: document.getElementById("icFluxCfgInput"),
  icFluxCond: document.getElementById("icFluxCondInput"),
  icFluxResolution: document.getElementById("icFluxResolutionInput"),
  icFluxFp16: document.getElementById("icFluxFp16Input"),
};
const controlValues = {
  strength: document.getElementById("strengthValue"),
  deltaGain: document.getElementById("deltaGainValue"),
  softness: document.getElementById("softnessValue"),
  choke: document.getElementById("chokeValue"),
  vitContext: document.getElementById("vitContextValue"),
  vitContrast: document.getElementById("vitContrastValue"),
  vitWarmth: document.getElementById("vitWarmthValue"),
  vitSaturation: document.getElementById("vitSaturationValue"),
  vitIdentity: document.getElementById("vitIdentityValue"),
  icFluxSeed: document.getElementById("icFluxSeedValue"),
  icFluxSteps: document.getElementById("icFluxStepsValue"),
  icFluxCfg: document.getElementById("icFluxCfgValue"),
  icFluxCond: document.getElementById("icFluxCondValue"),
  icFluxResolution: document.getElementById("icFluxResolutionValue"),
  icFluxFp16: document.getElementById("icFluxFp16Value"),
};
const sheetView = document.getElementById("sheetView");
const singleView = document.getElementById("singleView");
const imageTabs = document.getElementById("imageTabs");
const singleImage = document.getElementById("singleImage");
const jobMeta = document.getElementById("jobMeta");

let currentImages = [];
let latestUpdate = null;
let updateInstalled = false;
let icFluxReady = false;
let icFluxPolling = null;

function setStatus(text) {
  statusEl.textContent = text;
}

function setUpdateStatus(text) {
  updateStatus.textContent = text;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function summarizeMissingModels(payload) {
  return (payload.packages || [])
    .filter((item) => !item.present)
    .map((item) => item.label)
    .join(", ");
}

function renderIcFluxModelStatus(payload) {
  icFluxReady = Boolean(payload.ready);
  const icFluxSelected = backendSelect.value === "ic_flux_v2";
  const percent = Number(payload.percent || 0);
  icFluxDownloadProgress.value = icFluxReady ? 100 : percent;
  icFluxInlineDownloadButton.classList.toggle("hidden", !icFluxSelected || icFluxReady);

  if (payload.running) {
    icFluxDownloadButton.disabled = true;
    icFluxInlineDownloadButton.disabled = true;
    icFluxDownloadButton.textContent = "Downloading";
    icFluxInlineDownloadButton.textContent = "Downloading";
    icFluxModelStatus.textContent = `${percent.toFixed(1)}%`;
    const byteText = payload.total_bytes
      ? `${formatBytes(payload.downloaded_bytes)} / ${formatBytes(payload.total_bytes)}`
      : formatBytes(payload.downloaded_bytes);
    icFluxDownloadDetail.textContent = [payload.phase, payload.current_file, byteText].filter(Boolean).join(" | ");
  } else if (icFluxReady) {
    icFluxDownloadButton.disabled = true;
    icFluxInlineDownloadButton.disabled = true;
    icFluxDownloadButton.textContent = "Models Ready";
    icFluxInlineDownloadButton.textContent = "Models Ready";
    icFluxModelStatus.textContent = "Ready";
    const dirs = (payload.packages || []).map((item) => item.local_dir).join(" | ");
    icFluxDownloadDetail.textContent = `Required IC-Light and FLUX files are present locally. ${dirs}`;
  } else if (payload.status === "error") {
    icFluxDownloadButton.disabled = false;
    icFluxInlineDownloadButton.disabled = false;
    icFluxDownloadButton.textContent = "Retry Download";
    icFluxInlineDownloadButton.textContent = "Retry IC Flux Download";
    icFluxModelStatus.textContent = "Download failed";
    icFluxDownloadDetail.textContent = payload.error || "The selected external model source denied or failed the download.";
  } else {
    icFluxDownloadButton.disabled = false;
    icFluxInlineDownloadButton.disabled = false;
    icFluxDownloadButton.textContent = "Download IC Flux Models";
    icFluxInlineDownloadButton.textContent = "Download IC Flux Models";
    icFluxModelStatus.textContent = `Missing ${summarizeMissingModels(payload) || "models"}`;
    icFluxDownloadDetail.textContent = `${payload.disk_warning} ${payload.release_posture}`;
  }

  if (icFluxSelected) {
    runButton.disabled = !icFluxReady;
    setStatus(icFluxReady ? "IC Flux ready" : payload.running ? "Downloading IC Flux models" : "Download IC Flux models first");
  }
}

async function loadIcFluxModelStatus() {
  const response = await fetch("/api/models/ic-flux/status");
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "model status check failed");
  renderIcFluxModelStatus(payload);
  if (payload.running && !icFluxPolling) {
    icFluxPolling = window.setInterval(() => {
      loadIcFluxModelStatus().catch((error) => {
        window.clearInterval(icFluxPolling);
        icFluxPolling = null;
        icFluxDownloadDetail.textContent = error.message;
      });
    }, 1000);
  } else if (!payload.running && icFluxPolling) {
    window.clearInterval(icFluxPolling);
    icFluxPolling = null;
  }
}

function renderList(input, list) {
  list.textContent = "";
  const files = Array.from(input.files || []);
  if (!files.length) return;
  files.slice(0, 8).forEach((file) => {
    const item = document.createElement("li");
    item.textContent = file.name;
    list.appendChild(item);
  });
  if (files.length > 8) {
    const item = document.createElement("li");
    item.textContent = `+${files.length - 8} more frames`;
    list.appendChild(item);
  }
}

Object.entries(fields).forEach(([key, input]) => {
  input.addEventListener("change", () => renderList(input, lists[key]));
});

function updateControlReadouts() {
  controlValues.strength.textContent = `${Number(controls.strength.value).toFixed(2)}x`;
  controlValues.deltaGain.textContent = `${Number(controls.deltaGain.value).toFixed(1).replace(".0", "")}x`;
  controlValues.softness.textContent = `${controls.softness.value} px`;
  const choke = Number(controls.choke.value);
  controlValues.choke.textContent = choke > 0 ? `+${choke} px` : `${choke} px`;
  controlValues.vitContext.textContent = Number(controls.vitContext.value).toFixed(2);
  controlValues.vitContrast.textContent = Number(controls.vitContrast.value).toFixed(2);
  const warmth = Number(controls.vitWarmth.value);
  controlValues.vitWarmth.textContent = warmth > 0 ? `+${warmth.toFixed(2)}` : warmth.toFixed(2);
  controlValues.vitSaturation.textContent = Number(controls.vitSaturation.value).toFixed(2);
  controlValues.vitIdentity.textContent = Number(controls.vitIdentity.value).toFixed(2);
  controlValues.icFluxSeed.textContent = controls.icFluxSeed.value;
  controlValues.icFluxSteps.textContent = controls.icFluxSteps.value;
  controlValues.icFluxCfg.textContent = Number(controls.icFluxCfg.value).toFixed(2);
  controlValues.icFluxCond.textContent = Number(controls.icFluxCond.value).toFixed(2);
  controlValues.icFluxResolution.textContent = `${controls.icFluxResolution.value} px`;
  controlValues.icFluxFp16.textContent = controls.icFluxFp16.value === "1" ? "On" : "Off";
}

Object.values(controls).forEach((input) => input.addEventListener("input", updateControlReadouts));
updateControlReadouts();

function updateBackendReadout() {
  const backend = backendSelect.value;
  vitControls.classList.toggle("hidden", backend !== "pctnet_vit_proxy");
  icFluxControls.classList.toggle("hidden", backend !== "ic_flux_v2");
  if (backend === "pctnet_vit_proxy") {
    controlTitle.textContent = "ViT Controls";
    controlDescription.textContent = "PCT-Net ViT-style stronger foreground harmonization.";
    backendHint.textContent = "ViT pushes harder and can reveal more delta, but identity lock matters.";
    modelPill.textContent = "ViT";
    setStatus("Ready");
  } else if (backend === "ic_flux_v2") {
    controlTitle.textContent = "IC Flux Controls";
    controlDescription.textContent = "IC-Light V2 / FLUX external GPU relighting.";
    backendHint.textContent = "Internal/testing backend. Downloaded model files stay local and are not bundled with Latent Merge.";
    modelPill.textContent = "Flux";
    loadIcFluxModelStatus().catch((error) => setStatus(error.message));
  } else if (backend === "mean_match_stub") {
    controlTitle.textContent = "Baseline Controls";
    controlDescription.textContent = "Mean-match scaffold for quick conservative checks.";
    backendHint.textContent = "Mean Match is CPU-safe and subtle. Use it as a reference, not the final model.";
    modelPill.textContent = "Base";
    icFluxInlineDownloadButton.classList.add("hidden");
    runButton.disabled = false;
    setStatus("Ready");
  } else {
    controlTitle.textContent = "PCT Controls";
    controlDescription.textContent = "PCT-Net CNN, foreground-only output.";
    backendHint.textContent = "CNN is safer and more conservative. ViT is stronger, with more identity risk.";
    modelPill.textContent = "CNN";
    icFluxInlineDownloadButton.classList.add("hidden");
    runButton.disabled = false;
    setStatus("Ready");
  }
}

backendSelect.addEventListener("change", updateBackendReadout);
updateBackendReadout();

document.querySelectorAll("[data-browse]").forEach((button) => {
  button.addEventListener("click", () => {
    document.getElementById(button.dataset.browse).click();
  });
});

document.querySelectorAll(".dropzone").forEach((zone) => {
  const input = document.getElementById(zone.dataset.target);
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("dragging");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("dragging");
    input.files = event.dataTransfer.files;
    input.dispatchEvent(new Event("change"));
  });
});

async function loadGpus() {
  const response = await fetch("/api/gpus");
  const payload = await response.json();
  gpuSelect.textContent = "";
  payload.gpus.forEach((gpu) => {
    const option = document.createElement("option");
    option.value = gpu.id;
    option.textContent = gpu.label;
    gpuSelect.appendChild(option);
  });
}

async function loadUpdateStatus() {
  const response = await fetch("/api/update/status");
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "update check failed");

  latestUpdate = payload;
  updateInstalled = false;
  if (!payload.supported) {
    updateButton.disabled = true;
    updateButton.textContent = "Update Unavailable";
    setUpdateStatus("Linux updater only");
    return;
  }

  if (payload.update_available) {
    updateButton.disabled = false;
    updateButton.textContent = "Update";
    setUpdateStatus(`Current ${payload.current}; latest ${payload.latest}`);
    return;
  }

  updateButton.disabled = false;
  updateButton.textContent = "Check for Update";
  setUpdateStatus(`Current ${payload.current}`);
}

updateButton.addEventListener("click", async () => {
  if (updateInstalled) {
    setUpdateStatus("Close this app and restart ./bin/latent-merge-ui");
    return;
  }

  updateButton.disabled = true;
  const shouldDownload = latestUpdate && latestUpdate.update_available;
  updateButton.textContent = shouldDownload ? "Updating" : "Checking";
  setUpdateStatus(shouldDownload ? "Downloading latest release" : "Checking GitHub releases");

  try {
    if (!shouldDownload) {
      await loadUpdateStatus();
      return;
    }

    const response = await fetch("/api/update", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "update failed");
    updateInstalled = true;
    updateButton.disabled = false;
    updateButton.textContent = "Restart App";
    setUpdateStatus(`Installed ${payload.current}; restart to use it`);
  } catch (error) {
    updateButton.disabled = false;
    updateButton.textContent = "Retry Update";
    setUpdateStatus(error.message);
  }
});

icFluxDownloadButton.addEventListener("click", async () => {
  await startIcFluxModelDownload();
});

icFluxInlineDownloadButton.addEventListener("click", async () => {
  await startIcFluxModelDownload();
});

async function startIcFluxModelDownload() {
  icFluxDownloadButton.disabled = true;
  icFluxInlineDownloadButton.disabled = true;
  icFluxDownloadButton.textContent = "Starting";
  icFluxInlineDownloadButton.textContent = "Starting";
  icFluxDownloadDetail.textContent = "Preparing external model download";
  try {
    const response = await fetch("/api/models/ic-flux/download", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "model download failed");
    renderIcFluxModelStatus(payload);
    await loadIcFluxModelStatus();
  } catch (error) {
    icFluxDownloadButton.disabled = false;
    icFluxInlineDownloadButton.disabled = false;
    icFluxDownloadButton.textContent = "Retry Download";
    icFluxInlineDownloadButton.textContent = "Retry IC Flux Download";
    icFluxDownloadDetail.textContent = error.message;
  }
}

function activateSingle(index) {
  const image = currentImages[index];
  if (!image) return;
  Array.from(imageTabs.children).forEach((button, idx) => {
    button.classList.toggle("active", idx === index);
  });
  singleImage.src = image.url;
  singleImage.alt = image.label;
}

function renderOutputs(payload) {
  currentImages = payload.images || [];
  sheetView.classList.remove("empty");
  sheetView.innerHTML = "";
  const sheet = document.createElement("img");
  sheet.src = payload.contact_sheet;
  sheet.alt = "Contact sheet";
  sheetView.appendChild(sheet);

  imageTabs.textContent = "";
  currentImages.forEach((image, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = image.label;
    button.addEventListener("click", () => activateSingle(index));
    imageTabs.appendChild(button);
  });
  activateSingle(0);

  const seq = payload.sequence || {};
  const ctl = payload.controls || {};
  jobMeta.textContent = [
    payload.job_id,
    payload.backend,
    `strength ${ctl.adjustment_strength ?? "?"}x`,
    `delta ${ctl.delta_preview_gain ?? "?"}x`,
    ctl.vit_context !== undefined ? `context ${ctl.vit_context}` : null,
    ctl.ic_flux_steps !== undefined ? `steps ${ctl.ic_flux_steps}` : null,
    `A ${seq.cg_frames_uploaded || 0} frame(s), B ${seq.plate_frames_uploaded || 0} frame(s)`,
  ].filter(Boolean).join(" | ");
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-view]").forEach((node) => node.classList.remove("active"));
    button.classList.add("active");
    const sheet = button.dataset.view === "sheet";
    sheetView.classList.toggle("hidden", !sheet);
    singleView.classList.toggle("hidden", sheet);
  });
});

runButton.addEventListener("click", async () => {
  if (backendSelect.value === "ic_flux_v2" && !icFluxReady) {
    setStatus("Download IC Flux models first");
    return;
  }

  if (!fields.cg.files.length || !fields.plate.files.length) {
    setStatus("Choose A and B inputs first");
    return;
  }

  const form = new FormData();
  Array.from(fields.cg.files).forEach((file) => form.append("cg", file));
  Array.from(fields.plate.files).forEach((file) => form.append("plate", file));
  Array.from(fields.alpha.files).forEach((file) => form.append("alpha", file));
  form.append("gpu", gpuSelect.value || "cpu");
  form.append("backend", backendSelect.value || "pctnet");
  form.append("adjustment_strength", controls.strength.value);
  form.append("delta_preview_gain", controls.deltaGain.value);
  form.append("correction_softness_px", controls.softness.value);
  form.append("correction_choke_px", controls.choke.value);
  form.append("vit_context", controls.vitContext.value);
  form.append("vit_contrast", controls.vitContrast.value);
  form.append("vit_warmth", controls.vitWarmth.value);
  form.append("vit_saturation", controls.vitSaturation.value);
  form.append("vit_identity_lock", controls.vitIdentity.value);
  form.append("ic_flux_seed", controls.icFluxSeed.value);
  form.append("ic_flux_steps", controls.icFluxSteps.value);
  form.append("ic_flux_cfg", controls.icFluxCfg.value);
  form.append("ic_flux_cond_strength", controls.icFluxCond.value);
  form.append("ic_flux_resolution", controls.icFluxResolution.value);
  form.append("ic_flux_fp16", controls.icFluxFp16.value);

  runButton.disabled = true;
  setStatus(`Running ${backendSelect.options[backendSelect.selectedIndex].textContent}`);
  try {
    const response = await fetch("/api/run", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "run failed");
    renderOutputs(payload);
    setStatus("Done");
  } catch (error) {
    setStatus(error.message);
  } finally {
    runButton.disabled = false;
  }
});

loadGpus().catch((error) => setStatus(error.message));
loadIcFluxModelStatus().catch((error) => {
  icFluxModelStatus.textContent = "Model status unavailable";
  icFluxDownloadDetail.textContent = error.message;
});
loadUpdateStatus().catch((error) => {
  updateButton.textContent = "Retry Update";
  setUpdateStatus(error.message);
});
