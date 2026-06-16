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
