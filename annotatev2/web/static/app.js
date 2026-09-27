"use strict";

// ── State ────────────────────────────────────────────────────────────────
let photoTypes = [];
let optionalGroup = [];
let submissionId = sessionStorage.getItem("submission_id") || null;
let uploadedTypes = new Set();   // photo_type ids already sent to the server
let pending = {};                // photo_type id -> { file, crop: {x,y,width,height} (natural px), previewUrl }

let activeSlotId = null;         // which slot the crop modal is currently editing
let cropState = null;            // { box: {left, top, width, height} } in displayed px

// ── Boot ─────────────────────────────────────────────────────────────────

(async function init() {
  const res = await fetch("/api/photo_types");
  const data = await res.json();
  photoTypes = data.photo_types;
  optionalGroup = data.optional_group;

  renderSlots();
  persistYearInputs();

  const familyEl = document.getElementById("in-family");
  const savedFamily = sessionStorage.getItem("family_label");
  if (savedFamily) familyEl.value = savedFamily;
  familyEl.addEventListener("input", () => sessionStorage.setItem("family_label", familyEl.value));

  if (submissionId) {
    try {
      const r = await fetch(`/api/submissions/${submissionId}/photos`);
      if (r.ok) {
        const d = await r.json();
        for (const p of d.photos) {
          uploadedTypes.add(p.photo_type);
          markSlotSent(p.photo_type);
          const type = photoTypes.find((t) => t.id === p.photo_type);
          if (type) setYearInput(`birth-${type.person}`, p.birth_year);
          setYearInput(`year-${p.photo_type}`, p.photo_year);
        }
      } else {
        submissionId = null; // stale/unknown - a fresh submission is created on submit
      }
    } catch (e) {
      // ignore - slots just stay empty
    }
  }
  updateSubmitButton();

  document.getElementById("new-batch").addEventListener("click", () => {
    if (!confirm("Start a new family? This clears the current form (already-uploaded photos stay saved on the server).")) return;
    sessionStorage.removeItem("submission_id");
    sessionStorage.removeItem("family_label");
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith("year_input:")) sessionStorage.removeItem(key);
    }
    location.reload();
  });
})();

// ── Slot rendering ───────────────────────────────────────────────────────

function renderSlots() {
  const container = document.getElementById("slots");
  container.innerHTML = "";
  for (const type of photoTypes) {
    const card = document.createElement("div");
    card.className = "card slot-card";
    card.id = `slot-${type.id}`;
    // Your own birth year is asked once in the top card; each parent's lives
    // in their card. The year the photo was taken is per slot.
    const birthField = type.person === "self" ? "" : `
      <label for="birth-${type.person}">${capitalize(type.person)}'s year of birth</label>
      <input id="birth-${type.person}" class="year-input" type="number" inputmode="numeric" min="1900" placeholder="e.g. 1955">
    `;
    card.innerHTML = `
      <label>${type.label}${type.required ? "" : " (optional)"}</label>
      <p class="hint">${type.hint}</p>
      <div class="slot-preview" id="preview-${type.id}"></div>
      <input type="file" accept="image/*" id="file-${type.id}" class="slot-file-input">
      ${birthField}
      <label for="year-${type.id}">Year this photo was taken</label>
      <input id="year-${type.id}" class="year-input" type="number" inputmode="numeric" min="1900" placeholder="e.g. 2010">
      <p class="hint">Best guess is fine if you're not sure, but exact is better.</p>
      <p class="slot-status" id="status-${type.id}"></p>
    `;
    container.appendChild(card);
    document.getElementById(`file-${type.id}`).addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (file) openCropModal(type.id, file);
      e.target.value = ""; // allow picking the same file again later
    });
  }
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Keep typed years across a page refresh, like the family name.
function persistYearInputs() {
  for (const el of document.querySelectorAll(".year-input")) {
    const key = `year_input:${el.id}`;
    const saved = sessionStorage.getItem(key);
    if (saved) el.value = saved;
    el.addEventListener("input", () => sessionStorage.setItem(key, el.value));
  }
}

function setYearInput(id, value) {
  const el = document.getElementById(id);
  if (el && !el.value && value) {
    el.value = value;
    sessionStorage.setItem(`year_input:${id}`, String(value));
  }
}

// Returns {birth_year, photo_year} or throws with a participant-facing message.
function readYears(photoTypeId) {
  const type = photoTypes.find((t) => t.id === photoTypeId);
  const birthRaw = document.getElementById(`birth-${type.person}`).value.trim();
  const photoRaw = document.getElementById(`year-${photoTypeId}`).value.trim();
  const thisYear = new Date().getFullYear();
  const who = type.person === "self" ? "your" : `your ${type.person}'s`;
  if (!birthRaw) throw new Error(`Please enter ${who} year of birth (a best guess is fine).`);
  if (!photoRaw) throw new Error("Please enter the year this photo was taken (a best guess is fine).");
  const birth_year = Number(birthRaw);
  const photo_year = Number(photoRaw);
  if (!Number.isInteger(birth_year) || birth_year < 1900 || birth_year > thisYear) {
    throw new Error(`Year of birth should be a year between 1900 and ${thisYear}.`);
  }
  if (!Number.isInteger(photo_year) || photo_year < 1900 || photo_year > thisYear) {
    throw new Error(`Photo year should be a year between 1900 and ${thisYear}.`);
  }
  if (photo_year < birth_year) throw new Error("The photo year can't be before the year of birth.");
  return { birth_year, photo_year };
}

function setSlotStatus(photoTypeId, text, kind) {
  const el = document.getElementById(`status-${photoTypeId}`);
  el.textContent = text;
  el.classList.remove("ok", "err");
  if (kind) el.classList.add(kind);
}

function setSlotPreview(photoTypeId, imgUrl) {
  document.getElementById(`preview-${photoTypeId}`).innerHTML =
    imgUrl ? `<img src="${imgUrl}" alt="">` : "";
}

function markSlotSent(photoTypeId) {
  setSlotStatus(photoTypeId, "Sent ✓", "ok");
}

function currentReadyTypes() {
  // Either already sent (from a previous submit) or cropped-and-pending now.
  return new Set([...uploadedTypes, ...Object.keys(pending)]);
}

function updateSubmitButton() {
  const ready = currentReadyTypes();
  const requiredIds = photoTypes.filter((t) => t.required).map((t) => t.id);
  const requiredDone = requiredIds.every((id) => ready.has(id));
  const optionalDone = optionalGroup.some((id) => ready.has(id));
  const btn = document.getElementById("submit-all");
  const statusEl = document.getElementById("submit-status");
  const doneCount = ready.size;

  const allSent = photoTypes.every((t) => uploadedTypes.has(t.id) || !ready.has(t.id)) &&
    Object.keys(pending).length === 0 && uploadedTypes.size > 0;

  if (allSent && requiredDone && optionalDone) {
    statusEl.textContent = "All done — thank you!";
    btn.disabled = true;
    btn.textContent = "Submitted";
    return;
  }

  btn.textContent = "Submit photos";
  if (requiredDone && optionalDone) {
    statusEl.textContent = `${doneCount} of ${photoTypes.length} photos ready. Click submit to send them.`;
    btn.disabled = false;
  } else {
    const missing = [];
    if (!requiredDone) missing.push("both of your own photos");
    if (!optionalDone) missing.push("at least one parent photo");
    statusEl.textContent = `${doneCount} of ${photoTypes.length} selected — still need: ${missing.join(" and ")}.`;
    btn.disabled = true;
  }
}

// ── Crop modal ───────────────────────────────────────────────────────────

function openCropModal(photoTypeId, file) {
  activeSlotId = photoTypeId;

  const img = document.getElementById("crop-image");
  const url = URL.createObjectURL(file);
  img.onload = () => {
    const displayedW = img.clientWidth;
    const displayedH = img.clientHeight;
    cropState = { box: { left: 0, top: 0, width: displayedW, height: displayedH } }; // default: whole image
    layoutCropBox();
  };
  img.src = url;
  img._pendingFile = file; // stash the File object on the element for the confirm handler

  document.getElementById("crop-error").classList.add("hidden");
  document.getElementById("crop-modal").classList.remove("hidden");
}

function closeCropModal() {
  document.getElementById("crop-modal").classList.add("hidden");
  activeSlotId = null;
  cropState = null;
}

function layoutCropBox() {
  const box = document.getElementById("crop-box");
  const { left, top, width, height } = cropState.box;
  box.style.left = `${left}px`;
  box.style.top = `${top}px`;
  box.style.width = `${width}px`;
  box.style.height = `${height}px`;
}

function clampBox(box, maxW, maxH) {
  const MIN = 40;
  box.width = Math.max(MIN, Math.min(box.width, maxW));
  box.height = Math.max(MIN, Math.min(box.height, maxH));
  box.left = Math.max(0, Math.min(box.left, maxW - box.width));
  box.top = Math.max(0, Math.min(box.top, maxH - box.height));
  return box;
}

(function setupCropDragging() {
  const boxEl = document.getElementById("crop-box");
  let drag = null;

  function frameSize() {
    const img = document.getElementById("crop-image");
    return { w: img.clientWidth, h: img.clientHeight };
  }

  function pointerDown(e, mode) {
    e.preventDefault();
    const point = e.touches ? e.touches[0] : e;
    drag = { mode, startX: point.clientX, startY: point.clientY, startBox: { ...cropState.box } };
    window.addEventListener("mousemove", pointerMove);
    window.addEventListener("mouseup", pointerUp);
    window.addEventListener("touchmove", pointerMove, { passive: false });
    window.addEventListener("touchend", pointerUp);
  }

  function pointerMove(e) {
    if (!drag || !cropState) return;
    e.preventDefault();
    const point = e.touches ? e.touches[0] : e;
    const dx = point.clientX - drag.startX;
    const dy = point.clientY - drag.startY;
    const { w: maxW, h: maxH } = frameSize();
    const b = { ...drag.startBox };

    if (drag.mode === "move") {
      b.left = drag.startBox.left + dx;
      b.top = drag.startBox.top + dy;
    } else {
      if (drag.mode.includes("n")) { b.top = drag.startBox.top + dy; b.height = drag.startBox.height - dy; }
      if (drag.mode.includes("s")) { b.height = drag.startBox.height + dy; }
      if (drag.mode.includes("w")) { b.left = drag.startBox.left + dx; b.width = drag.startBox.width - dx; }
      if (drag.mode.includes("e")) { b.width = drag.startBox.width + dx; }
    }
    cropState.box = clampBox(b, maxW, maxH);
    layoutCropBox();
  }

  function pointerUp() {
    drag = null;
    window.removeEventListener("mousemove", pointerMove);
    window.removeEventListener("mouseup", pointerUp);
    window.removeEventListener("touchmove", pointerMove);
    window.removeEventListener("touchend", pointerUp);
  }

  boxEl.addEventListener("mousedown", (e) => { if (e.target === boxEl) pointerDown(e, "move"); });
  boxEl.addEventListener("touchstart", (e) => { if (e.target === boxEl) pointerDown(e, "move"); }, { passive: false });
  for (const handle of boxEl.querySelectorAll(".handle")) {
    const mode = handle.dataset.handle;
    handle.addEventListener("mousedown", (e) => pointerDown(e, mode));
    handle.addEventListener("touchstart", (e) => pointerDown(e, mode), { passive: false });
  }
})();

document.getElementById("crop-cancel").addEventListener("click", closeCropModal);

document.getElementById("crop-confirm").addEventListener("click", () => {
  const img = document.getElementById("crop-image");
  const file = img._pendingFile;
  const scaleX = img.naturalWidth / img.clientWidth;
  const scaleY = img.naturalHeight / img.clientHeight;

  const crop = {
    x: Math.round(cropState.box.left * scaleX),
    y: Math.round(cropState.box.top * scaleY),
    width: Math.round(cropState.box.width * scaleX),
    height: Math.round(cropState.box.height * scaleY),
  };

  // Render exactly the cropped region into a canvas so the slot preview
  // shows what will actually be kept, not the full uncropped photo.
  const canvas = document.createElement("canvas");
  canvas.width = crop.width;
  canvas.height = crop.height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(img, crop.x, crop.y, crop.width, crop.height, 0, 0, crop.width, crop.height);

  const photoTypeId = activeSlotId;
  pending[photoTypeId] = { file, crop, previewUrl: canvas.toDataURL("image/jpeg", 0.9) };

  setSlotPreview(photoTypeId, pending[photoTypeId].previewUrl);
  setSlotStatus(photoTypeId, "Ready to submit", null);
  updateSubmitButton();
  closeCropModal();
});

// ── Submit ───────────────────────────────────────────────────────────────

async function ensureSubmission() {
  if (submissionId) return submissionId;
  const familyEl = document.getElementById("in-family");
  const errEl = document.getElementById("family-error");
  const family_label = familyEl.value.trim();
  if (!family_label) {
    errEl.textContent = "Please enter a family / subject name first.";
    errEl.classList.remove("hidden");
    familyEl.focus();
    return null;
  }
  errEl.classList.add("hidden");
  const res = await fetch("/api/submissions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ family_label }),
  });
  if (!res.ok) throw new Error("Could not start submission");
  const data = await res.json();
  submissionId = data.submission_id;
  sessionStorage.setItem("submission_id", submissionId);
  return submissionId;
}

async function uploadOne(photoTypeId, entry, years) {
  const form = new FormData();
  form.append("submission_id", submissionId);
  form.append("photo_type", photoTypeId);
  form.append("crop", JSON.stringify(entry.crop));
  form.append("birth_year", String(years.birth_year));
  form.append("photo_year", String(years.photo_year));
  form.append("image", entry.file, entry.file.name || `${photoTypeId}.jpg`);

  const res = await fetch("/api/photos", { method: "POST", body: form });
  if (res.status === 422) {
    const data = await res.json();
    throw new Error((data.detail && data.detail.detail) || data.detail || "please choose a different photo");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "upload failed");
  }
}

document.getElementById("submit-all").addEventListener("click", async () => {
  const errEl = document.getElementById("submit-error");
  errEl.classList.add("hidden");
  const btn = document.getElementById("submit-all");

  // Check every pending slot's years up front so nothing half-uploads
  // because one card is missing a year.
  const yearsBySlot = {};
  let missingYears = 0;
  for (const photoTypeId of Object.keys(pending)) {
    try {
      yearsBySlot[photoTypeId] = readYears(photoTypeId);
    } catch (e) {
      missingYears += 1;
      setSlotStatus(photoTypeId, e.message, "err");
    }
  }
  if (missingYears > 0) {
    errEl.textContent = `Please fill in the years on the highlighted photo(s) - a best guess is fine.`;
    errEl.classList.remove("hidden");
    return;
  }

  const sid = await ensureSubmission().catch((e) => {
    errEl.textContent = e.message || String(e);
    errEl.classList.remove("hidden");
    return null;
  });
  if (!sid) return;

  btn.disabled = true;
  btn.textContent = "Submitting…";

  const entries = Object.entries(pending);
  let failures = 0;
  for (const [photoTypeId, entry] of entries) {
    setSlotStatus(photoTypeId, "Uploading…", null);
    try {
      await uploadOne(photoTypeId, entry, yearsBySlot[photoTypeId]);
      uploadedTypes.add(photoTypeId);
      delete pending[photoTypeId];
      markSlotSent(photoTypeId);
    } catch (e) {
      failures += 1;
      setSlotStatus(photoTypeId, e.message || String(e), "err");
    }
  }

  if (failures > 0) {
    errEl.textContent = `${failures} photo(s) failed to upload - fix the highlighted slot(s) and submit again.`;
    errEl.classList.remove("hidden");
  }
  updateSubmitButton();
});
