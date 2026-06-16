async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`${url} -> ${res.status}`);
  }
  return res.json();
}

function cardPayload(card) {
  return {
    subject_id: card.dataset.subject,
    photo_type: card.dataset.photoType,
    candidate_id: card.dataset.id,
  };
}

document.addEventListener("DOMContentLoaded", () => {
  // --- select / deselect ---
  document.querySelectorAll(".select-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card");
      const selected = !card.classList.contains("selected");
      try {
        const data = await postJson("/api/select", { ...cardPayload(card), selected });
        card.classList.toggle("selected", data.status === "selected");
        btn.textContent = data.status === "selected" ? "Selected ✓" : "Select";
      } catch (e) {
        alert("Failed to update selection: " + e);
      }
    });
  });

  // --- crop modal ---
  const modal = document.getElementById("crop-modal");
  const cropImage = document.getElementById("crop-image");
  let cropper = null;
  let activeCard = null;

  function closeModal() {
    if (cropper) {
      cropper.destroy();
      cropper = null;
    }
    activeCard = null;
    modal.classList.add("hidden");
  }

  document.querySelectorAll(".crop-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeCard = btn.closest(".card");
      cropImage.src = activeCard.dataset.original;
      modal.classList.remove("hidden");
      cropImage.onload = () => {
        if (cropper) cropper.destroy();
        cropper = new Cropper(cropImage, { viewMode: 1, autoCropArea: 1 });
      };
    });
  });

  document.getElementById("crop-cancel").addEventListener("click", closeModal);

  document.getElementById("crop-save").addEventListener("click", async () => {
    if (!cropper || !activeCard) return;
    const data = cropper.getData(true);
    try {
      const result = await postJson("/api/crop", {
        ...cardPayload(activeCard),
        left: data.x,
        top: data.y,
        right: data.x + data.width,
        bottom: data.y + data.height,
      });
      const thumb = activeCard.querySelector(".thumb");
      thumb.src = result.cropped_url + "?t=" + Date.now();
    } catch (e) {
      alert("Failed to save crop: " + e);
    } finally {
      closeModal();
    }
  });

  // --- reset crop ---
  document.querySelectorAll(".uncrop-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card");
      try {
        const result = await postJson("/api/uncrop", { ...cardPayload(card), selected: false });
        card.querySelector(".thumb").src = result.image_url + "?t=" + Date.now();
        btn.remove();
      } catch (e) {
        alert("Failed to reset crop: " + e);
      }
    });
  });
});

async function exportLocal() {
  const res = await fetch("/api/export/local", { method: "POST" });
  const data = await res.json();
  alert("Saved selected photos to " + data.output_dir);
}

async function exportHtml() {
  const res = await fetch("/api/export/html", { method: "POST" });
  const data = await res.json();
  alert("Wrote gallery to " + data.path);
}
