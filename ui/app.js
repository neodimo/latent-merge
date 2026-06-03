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
const statusEl = document.getElementById("status");
const gpuSelect = document.getElementById("gpuSelect");
const backendSelect = document.getElementById("backendSelect");
const backendName = document.getElementById("backendName");
const backendDescription = document.getElementById("backendDescription");
const backendTagline = document.getElementById("backendTagline");
const parameterControls = document.getElementById("parameterControls");
const sheetView = document.getElementById("sheetView");
const singleView = document.getElementById("singleView");
const imageTabs = document.getElementById("imageTabs");
const singleImage = document.getElementById("singleImage");
const jobMeta = document.getElementById("jobMeta");

let currentImages = [];
let backends = [];

function setStatus(text) {
  statusEl.textContent = text;
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

async function loadBackends() {
  const response = await fetch("/api/backends");
  const payload = await response.json();
  backends = payload.backends || [];
  backendSelect.textContent = "";
  backends.forEach((backend) => {
    const option = document.createElement("option");
    option.value = backend.id;
    option.textContent = backend.name;
    backendSelect.appendChild(option);
  });
  if (backends.some((backend) => backend.id === "pctnet_vit_proxy")) {
    backendSelect.value = "pctnet_vit_proxy";
  }
  renderBackendControls();
}

function valueLabel(param, value) {
  const numeric = Number(value);
  if (param.key === "warmth") {
    if (numeric < -0.02) return `${numeric.toFixed(2)} cool`;
    if (numeric > 0.02) return `${numeric.toFixed(2)} warm`;
    return "0.00 neutral";
  }
  if (param.key === "delta_display_gain") return `${numeric.toFixed(2)}x`;
  return numeric.toFixed(2);
}

function renderBackendControls() {
  const backend = backends.find((item) => item.id === backendSelect.value) || backends[0];
  if (!backend) return;

  backendName.textContent = backend.name;
  backendDescription.textContent = backend.description;
  backendTagline.textContent = backend.tagline;
  parameterControls.textContent = "";

  if (!backend.parameters.length) {
    const empty = document.createElement("p");
    empty.className = "empty-params";
    empty.textContent = "No exposed controls for this baseline.";
    parameterControls.appendChild(empty);
    return;
  }

  backend.parameters.forEach((param) => {
    const row = document.createElement("label");
    row.className = "parameter";
    row.dataset.param = param.key;

    const head = document.createElement("span");
    head.className = "parameter-head";

    const name = document.createElement("strong");
    name.textContent = param.label;

    const output = document.createElement("span");
    output.className = "parameter-value";
    output.textContent = valueLabel(param, param.default);

    head.append(name, output);

    const input = document.createElement("input");
    input.type = "range";
    input.min = param.min;
    input.max = param.max;
    input.step = param.step;
    input.value = param.default;
    input.name = `param_${param.key}`;
    input.addEventListener("input", () => {
      output.textContent = valueLabel(param, input.value);
    });

    const hints = document.createElement("span");
    hints.className = "parameter-hints";
    const low = document.createElement("span");
    low.textContent = param.low;
    const high = document.createElement("span");
    high.textContent = param.high;
    hints.append(low, high);

    row.append(head, input, hints);
    parameterControls.appendChild(row);
  });
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
  jobMeta.textContent = `${payload.job_id} | ${payload.backend} | A ${seq.cg_frames_uploaded || 0} frame(s), B ${seq.plate_frames_uploaded || 0} frame(s)`;
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
  form.append("backend", backendSelect.value || "mean_match_stub");
  parameterControls.querySelectorAll("input[name^='param_']").forEach((input) => {
    form.append(input.name, input.value);
  });

  runButton.disabled = true;
  setStatus("Running");
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

backendSelect.addEventListener("change", renderBackendControls);

Promise.all([loadGpus(), loadBackends()]).catch((error) => setStatus(error.message));
