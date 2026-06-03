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
};
const sheetView = document.getElementById("sheetView");
const singleView = document.getElementById("singleView");
const imageTabs = document.getElementById("imageTabs");
const singleImage = document.getElementById("singleImage");
const jobMeta = document.getElementById("jobMeta");

let currentImages = [];
let latestUpdate = null;
let updateInstalled = false;

function setStatus(text) {
  statusEl.textContent = text;
}

function setUpdateStatus(text) {
  updateStatus.textContent = text;
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
}

Object.values(controls).forEach((input) => input.addEventListener("input", updateControlReadouts));
updateControlReadouts();

function updateBackendReadout() {
  const backend = backendSelect.value;
  vitControls.classList.toggle("hidden", backend !== "pctnet_vit_proxy");
  if (backend === "pctnet_vit_proxy") {
    controlTitle.textContent = "ViT Controls";
    controlDescription.textContent = "PCT-Net ViT-style stronger foreground harmonization.";
    backendHint.textContent = "ViT pushes harder and can reveal more delta, but identity lock matters.";
    modelPill.textContent = "ViT";
    setStatus("Ready");
  } else if (backend === "mean_match_stub") {
    controlTitle.textContent = "Baseline Controls";
    controlDescription.textContent = "Mean-match scaffold for quick conservative checks.";
    backendHint.textContent = "Mean Match is CPU-safe and subtle. Use it as a reference, not the final model.";
    modelPill.textContent = "Base";
    setStatus("Ready");
  } else {
    controlTitle.textContent = "PCT Controls";
    controlDescription.textContent = "PCT-Net CNN, foreground-only output.";
    backendHint.textContent = "CNN is safer and more conservative. ViT is stronger, with more identity risk.";
    modelPill.textContent = "CNN";
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
loadUpdateStatus().catch((error) => {
  updateButton.textContent = "Retry Update";
  setUpdateStatus(error.message);
});
