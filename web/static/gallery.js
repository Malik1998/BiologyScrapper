"use strict";
// Lightbox gallery used by index.html and library.html.
// renderImageSections() populates window.lbSections before calling openLightbox().

window.lbSections = []; // array of arrays: lbSections[sectionIdx][cardIdx]

let lbCards = [];
let lbIdx   = 0;

window.openLightbox = function (sectionIdx, cardIdx) {
  lbCards = window.lbSections[sectionIdx] || [];
  lbIdx   = Math.max(0, Math.min(cardIdx, lbCards.length - 1));
  if (!lbCards.length) return;
  document.getElementById("lightbox").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  showSlide();
};

function closeLightbox() {
  document.getElementById("lightbox").classList.add("hidden");
  document.body.style.overflow = "";
}

function showSlide() {
  const c = lbCards[lbIdx];

  // Image
  const img = document.getElementById("lb-img");
  img.style.opacity = "0";
  img.src = c.image_url;
  img.onload = () => { img.style.opacity = "1"; };

  // Text
  setText("lb-title", c.title || "");
  setText("lb-desc",  c.description || "");

  const dims = c.width && c.height ? `${c.width} × ${c.height} px` : "";
  const qstr = c.query ? `query: "${c.query}"` : "";
  setText("lb-meta", [dims, qstr].filter(Boolean).join("  ·  "));

  // Source link
  const src = document.getElementById("lb-source");
  src.href = c.page_url || "#";
  src.style.display = c.page_url ? "" : "none";

  // Counter + nav
  document.getElementById("lb-counter").textContent = `${lbIdx + 1} / ${lbCards.length}`;
  document.getElementById("lb-prev").style.visibility = lbIdx > 0 ? "visible" : "hidden";
  document.getElementById("lb-next").style.visibility = lbIdx < lbCards.length - 1 ? "visible" : "hidden";
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function lbPrev() { if (lbIdx > 0) { lbIdx--; showSlide(); } }
function lbNext() { if (lbIdx < lbCards.length - 1) { lbIdx++; showSlide(); } }

document.addEventListener("DOMContentLoaded", () => {
  const lb = document.getElementById("lightbox");
  if (!lb) return;

  document.getElementById("lb-close").addEventListener("click", closeLightbox);
  document.getElementById("lb-prev").addEventListener("click", lbPrev);
  document.getElementById("lb-next").addEventListener("click", lbNext);

  // Click backdrop to close
  lb.addEventListener("click", e => { if (e.target === lb) closeLightbox(); });

  // Keyboard
  document.addEventListener("keydown", e => {
    if (lb.classList.contains("hidden")) return;
    if (e.key === "ArrowLeft")  lbPrev();
    if (e.key === "ArrowRight") lbNext();
    if (e.key === "Escape")     closeLightbox();
  });
});

// ── Per-image metadata modal ──────────────────────────────────────────────────
// Wires up any ".meta-btn" inside a ".img-card"/".card" element (index.html,
// library.html, subject.html all use this via delegated click handling) to a
// modal that lets a non-programmer either click through a form built from
// config/image_meta_schema.json, or paste/edit the raw JSON directly.

function galEscHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const metaState = { schema: null, values: {}, mode: "form", card: null, subjectId: "", photoType: "", candidateId: "" };

function metaCardPayload(card) {
  return {
    subjectId: card.dataset.subject,
    photoType: card.dataset.photoType || card.dataset.pt,
    candidateId: card.dataset.id,
  };
}

function renderMetaFormField(field, value) {
  const id = `meta-field-${field.key}`;
  let control;
  if (field.type === "bool") {
    const v = value === true ? "true" : value === false ? "false" : "";
    control = `<select id="${id}">
      <option value="" ${v === "" ? "selected" : ""}>Unknown</option>
      <option value="true" ${v === "true" ? "selected" : ""}>Yes</option>
      <option value="false" ${v === "false" ? "selected" : ""}>No</option>
    </select>`;
  } else if (field.type === "enum") {
    const opts = (field.options || []).map(o =>
      `<option value="${galEscHtml(o)}" ${value === o ? "selected" : ""}>${galEscHtml(o)}</option>`
    ).join("");
    control = `<select id="${id}"><option value="" ${!value ? "selected" : ""}>Unknown</option>${opts}</select>`;
  } else if (field.type === "number") {
    control = `<input id="${id}" type="number" step="any" value="${value == null ? "" : galEscHtml(value)}">`;
  } else {
    control = `<textarea id="${id}" rows="2">${value == null ? "" : galEscHtml(value)}</textarea>`;
  }
  return `<label class="meta-field"><span class="meta-field-label">${galEscHtml(field.label)}</span>${control}</label>`;
}

function readMetaFormField(field) {
  const el = document.getElementById(`meta-field-${field.key}`);
  if (!el) return undefined;
  const raw = el.value;
  if (field.type === "bool") return raw === "" ? null : raw === "true";
  if (field.type === "enum") return raw === "" ? null : raw;
  if (field.type === "number") return raw === "" ? null : Number(raw);
  return raw;
}

function syncMetaFormIntoValues() {
  if (metaState.mode !== "form" || !metaState.schema) return;
  for (const field of metaState.schema) {
    const v = readMetaFormField(field);
    if (v !== undefined) metaState.values[field.key] = v;
  }
}

function renderMetaModal() {
  const form = document.getElementById("meta-form");
  const jsonBox = document.getElementById("meta-json");
  if (!form || !jsonBox) return;
  if (metaState.mode === "form") {
    form.innerHTML = metaState.schema.map(f => renderMetaFormField(f, metaState.values[f.key])).join("");
    form.classList.remove("hidden");
    jsonBox.classList.add("hidden");
  } else {
    jsonBox.value = JSON.stringify(metaState.values, null, 2);
    form.classList.add("hidden");
    jsonBox.classList.remove("hidden");
  }
  document.querySelectorAll(".meta-mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === metaState.mode));
}

function setMetaMode(mode) {
  if (mode === metaState.mode) return;
  if (metaState.mode === "form") {
    syncMetaFormIntoValues();
  } else {
    try {
      metaState.values = JSON.parse(document.getElementById("meta-json").value || "{}");
    } catch (e) {
      alert("Invalid JSON: " + e.message);
      return;
    }
  }
  metaState.mode = mode;
  renderMetaModal();
}

async function openMetaModal(card) {
  const modal = document.getElementById("meta-modal");
  if (!modal) return;
  const { subjectId, photoType, candidateId } = metaCardPayload(card);
  metaState.card = card;
  metaState.subjectId = subjectId;
  metaState.photoType = photoType;
  metaState.candidateId = candidateId;
  metaState.mode = "form";

  modal.classList.remove("hidden");
  document.getElementById("meta-form").innerHTML = `<p class="loading-pulse">Loading&hellip;</p>`;
  document.getElementById("meta-json").classList.add("hidden");

  try {
    const res = await fetch(`/api/meta/${subjectId}/${photoType}/${candidateId}`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    metaState.schema = data.fields;
    metaState.values = { ...data.suggested, ...data.saved };
    renderMetaModal();
  } catch (e) {
    document.getElementById("meta-form").innerHTML = `<p class="err">Failed to load metadata: ${galEscHtml(e.message)}</p>`;
  }
}

function closeMetaModal() {
  document.getElementById("meta-modal").classList.add("hidden");
  metaState.card = null;
}

async function saveMetaModal() {
  if (metaState.mode === "form") syncMetaFormIntoValues();
  else {
    try {
      metaState.values = JSON.parse(document.getElementById("meta-json").value || "{}");
    } catch (e) {
      alert("Invalid JSON: " + e.message);
      return;
    }
  }
  try {
    const res = await fetch("/api/meta", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject_id: metaState.subjectId,
        photo_type: metaState.photoType,
        candidate_id: metaState.candidateId,
        meta: metaState.values,
      }),
    });
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    if (metaState.card) {
      const hasMeta = Object.keys(data.meta || {}).length > 0;
      metaState.card.classList.toggle("has-meta", hasMeta);
      const btn = metaState.card.querySelector(".meta-btn");
      if (btn) btn.textContent = hasMeta ? "Meta ✓" : "Meta";
    }
    closeMetaModal();
  } catch (e) {
    alert("Failed to save metadata: " + e.message);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const modal = document.getElementById("meta-modal");
  if (!modal) return;

  document.addEventListener("click", e => {
    const btn = e.target.closest(".meta-btn");
    if (!btn) return;
    const card = btn.closest(".img-card, .card");
    if (card) openMetaModal(card);
  });

  document.querySelectorAll(".meta-mode-btn").forEach(b => {
    b.addEventListener("click", () => setMetaMode(b.dataset.mode));
  });
  document.getElementById("meta-cancel").addEventListener("click", closeMetaModal);
  document.getElementById("meta-save").addEventListener("click", saveMetaModal);
  modal.addEventListener("click", e => { if (e.target === modal) closeMetaModal(); });
});
