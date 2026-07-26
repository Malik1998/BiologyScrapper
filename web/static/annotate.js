// FLR reliability test (/annotate). Standalone page: name gate, then one
// photo + a schema-driven form at a time (config/annotation_schema.json),
// mirroring the form/JSON toggle pattern from gallery.js's meta modal.
// Also lets a rater browse + fix their own already-submitted scores
// ("my scored photos" panel) without disturbing their place in the queue.

const FLR_OPTIONS = [
  { value: "0", label: "0 - none/firm" },
  { value: "1", label: "1" },
  { value: "2", label: "2" },
  { value: "3", label: "3" },
  { value: "4", label: "4 - severe" },
  { value: "NA", label: "NA - not scoreable in this photo" },
];

// state.editingImageId is set while reviewing/fixing an already-submitted
// photo (opened from the "my scored photos" panel) instead of scoring the
// next new one; submitting in that mode returns to the panel rather than
// advancing the queue.
const state = { name: "", schema: null, mode: "form", values: {}, image: null, editingImageId: null };

function annEscHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function storedName() {
  return localStorage.getItem("annotate_rater_name") || "";
}

function renderField(field, value) {
  const id = `ann-field-${field.key}`;
  let control;
  if (field.type === "flr_score") {
    const opts = FLR_OPTIONS.map(o =>
      `<option value="${o.value}" ${value === o.value ? "selected" : ""}>${annEscHtml(o.label)}</option>`
    ).join("");
    control = `<select id="${id}"><option value="" ${!value ? "selected" : ""}>Unscored</option>${opts}</select>`;
  } else if (field.type === "enum") {
    const opts = (field.options || []).map(o =>
      `<option value="${annEscHtml(o)}" ${value === o ? "selected" : ""}>${annEscHtml(o)}</option>`
    ).join("");
    control = `<select id="${id}"><option value="" ${!value ? "selected" : ""}>Unset</option>${opts}</select>`;
  } else {
    control = `<input id="${id}" type="text" value="${value == null ? "" : annEscHtml(value)}">`;
  }
  return `<label class="meta-field"><span class="meta-field-label">${annEscHtml(field.label)}</span>${control}</label>`;
}

function readField(field) {
  const el = document.getElementById(`ann-field-${field.key}`);
  if (!el) return undefined;
  return el.value === "" ? null : el.value;
}

function syncFormIntoValues() {
  if (state.mode !== "form" || !state.schema) return;
  for (const field of state.schema.fields) {
    const v = readField(field);
    if (v !== undefined) state.values[field.key] = v;
  }
}

function renderScores() {
  const form = document.getElementById("ann-form");
  const jsonBox = document.getElementById("ann-json");
  if (state.mode === "form") {
    form.innerHTML = state.schema.fields.map(f => renderField(f, state.values[f.key])).join("");
    form.classList.remove("hidden");
    jsonBox.classList.add("hidden");
  } else {
    jsonBox.value = JSON.stringify(state.values, null, 2);
    form.classList.add("hidden");
    jsonBox.classList.remove("hidden");
  }
  document.querySelectorAll(".ann-mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === state.mode));
}

function setMode(mode) {
  if (mode === state.mode) return;
  if (state.mode === "form") {
    syncFormIntoValues();
  } else {
    try {
      state.values = JSON.parse(document.getElementById("ann-json").value || "{}");
    } catch (e) {
      alert("Invalid JSON: " + e.message);
      return;
    }
  }
  state.mode = mode;
  renderScores();
}

function emptyValues() {
  const v = {};
  for (const field of state.schema.fields) v[field.key] = null;
  return v;
}

function updateProgress(progress) {
  document.getElementById("progress-text").textContent = `${progress.done}/${progress.total} photos scored`;
  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  document.getElementById("progress-bar-fill").style.width = `${pct}%`;
}

function showBody(showDone) {
  document.getElementById("mine-panel").classList.add("hidden");
  document.getElementById("done-message").classList.toggle("hidden", !showDone);
  document.getElementById("annotate-body").classList.toggle("hidden", showDone);
}

function loadPhotoIntoForm(image, savedScores, comment) {
  state.image = image;
  state.mode = "form";
  state.values = savedScores ? { ...savedScores } : emptyValues();
  document.getElementById("ann-comment").value = comment || "";
  document.getElementById("ann-error").classList.add("hidden");

  document.getElementById("annotate-image").src = image.image_url;
  document.getElementById("annotate-context").textContent =
    `${image.relation_label} pair #${image.pair_index} — this photo: ${image.role_label}`;

  document.getElementById("edit-banner").classList.toggle("hidden", !state.editingImageId);
  document.getElementById("ann-submit").textContent = state.editingImageId ? "Save changes" : "Submit & next photo";

  renderScores();
}

function applyNextPayload(payload) {
  updateProgress(payload.progress);
  if (!payload.image) {
    showBody(true);
    return;
  }
  showBody(false);
  loadPhotoIntoForm(payload.image, null, "");
}

async function loadNext() {
  state.editingImageId = null;
  const res = await fetch(`/api/annotate/next?name=${encodeURIComponent(state.name)}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  applyNextPayload(await res.json());
}

function mineItemLabel(item) {
  const scored = Object.entries(item.scores || {})
    .filter(([, v]) => v !== null && v !== "")
    .map(([k, v]) => `${k}=${v}`)
    .join(", ") || "no scores set";
  return scored;
}

async function showMinePanel() {
  const res = await fetch(`/api/annotate/mine?name=${encodeURIComponent(state.name)}`);
  if (!res.ok) return;
  const { items } = await res.json();

  document.getElementById("done-message").classList.add("hidden");
  document.getElementById("annotate-body").classList.add("hidden");
  document.getElementById("mine-panel").classList.remove("hidden");

  document.getElementById("mine-empty").classList.toggle("hidden", items.length > 0);
  const list = document.getElementById("mine-list");
  list.innerHTML = items.map((item, i) => `
    <div class="mine-item" data-index="${i}">
      <img src="${item.image_url}" loading="lazy">
      <div class="mine-item-info">
        <div class="mine-item-title">${annEscHtml(item.relation_label)} pair #${annEscHtml(item.pair_index)} — ${annEscHtml(item.role_label)}</div>
        <div>${annEscHtml(mineItemLabel(item))}</div>
        ${item.comment ? `<div class="mine-item-comment">"${annEscHtml(item.comment)}"</div>` : ""}
      </div>
      <button class="btn btn-ghost mine-edit-btn" type="button" data-index="${i}">Edit</button>
    </div>
  `).join("");

  list.querySelectorAll(".mine-edit-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const item = items[Number(btn.dataset.index)];
      state.editingImageId = item.image_id;
      showBody(false);
      loadPhotoIntoForm(item, item.scores, item.comment);
    });
  });
}

async function submitCurrent() {
  syncFormIntoValues();
  const errEl = document.getElementById("ann-error");
  errEl.classList.add("hidden");
  const wasEditing = state.editingImageId;
  try {
    const res = await fetch("/api/annotate/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: state.name,
        image_id: state.image.image_id,
        scores: state.values,
        comment: document.getElementById("ann-comment").value,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || res.statusText);
    }
    const payload = await res.json();
    updateProgress(payload.progress);
    if (wasEditing) {
      state.editingImageId = null;
      await showMinePanel();
    } else {
      applyNextPayload(payload);
    }
  } catch (e) {
    errEl.textContent = "Failed to save: " + e.message;
    errEl.classList.remove("hidden");
  }
}

async function startSession(name) {
  state.name = name;
  localStorage.setItem("annotate_rater_name", name);
  document.getElementById("rater-name").textContent = name;

  const gateError = document.getElementById("gate-error");
  gateError.classList.add("hidden");

  try {
    if (!state.schema) {
      state.schema = await (await fetch("/api/annotate/schema")).json();
      document.getElementById("scale-note").textContent = state.schema.scale_note || "";
    }
    await loadNext();
    document.getElementById("gate").classList.add("hidden");
    document.getElementById("session").classList.remove("hidden");
  } catch (e) {
    gateError.textContent = e.message;
    gateError.classList.remove("hidden");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const nameInput = document.getElementById("gate-name");
  nameInput.value = storedName();

  document.getElementById("gate-start").addEventListener("click", () => {
    const name = nameInput.value.trim();
    if (!name) {
      const gateError = document.getElementById("gate-error");
      gateError.textContent = "Please enter your name.";
      gateError.classList.remove("hidden");
      return;
    }
    startSession(name);
  });
  nameInput.addEventListener("keydown", e => { if (e.key === "Enter") document.getElementById("gate-start").click(); });

  document.getElementById("switch-name").addEventListener("click", () => {
    document.getElementById("session").classList.add("hidden");
    document.getElementById("gate").classList.remove("hidden");
  });

  document.getElementById("show-mine").addEventListener("click", showMinePanel);
  document.getElementById("mine-close").addEventListener("click", () => loadNext());
  document.getElementById("edit-cancel").addEventListener("click", () => loadNext());

  document.querySelectorAll(".ann-mode-btn").forEach(b => {
    b.addEventListener("click", () => setMode(b.dataset.mode));
  });
  document.getElementById("ann-submit").addEventListener("click", submitCurrent);

  const auto = storedName();
  if (auto) startSession(auto);
});
