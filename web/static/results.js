// /annotate/results - read-only view of everything everyone has scored so
// far, grouped by photo. Pulls field labels from the same schema the
// scoring form uses so keys show up human-readable here too.

function resEscHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function renderRatersSummary(raters) {
  const el = document.getElementById("raters-summary");
  if (!raters.length) {
    el.innerHTML = `<p>No one has started scoring yet.</p>`;
    return;
  }
  el.innerHTML = raters.map(r => `
    <div class="rater-chip ${r.complete ? "rater-chip-complete" : ""}">
      <strong>${resEscHtml(r.display_name)}</strong> — ${r.done}/${r.total}${r.complete ? " ✓" : ""}
    </div>
  `).join("");
}

function renderScores(scores, labelByKey) {
  const entries = Object.entries(scores || {}).filter(([, v]) => v !== null && v !== "");
  if (!entries.length) return `<span class="response-empty">no scores set</span>`;
  return entries.map(([k, v]) => `<span class="score-chip"><span class="score-chip-label">${resEscHtml(labelByKey[k] || k)}</span> ${resEscHtml(v)}</span>`).join("");
}

function renderImage(image, labelByKey) {
  const responses = image.responses.map(r => `
    <div class="response-card">
      <div class="response-rater">${resEscHtml(r.rater)}</div>
      <div class="response-scores">${renderScores(r.scores, labelByKey)}</div>
      ${r.comment ? `<div class="response-comment">"${resEscHtml(r.comment)}"</div>` : ""}
    </div>
  `).join("");

  return `
    <div class="result-item">
      <img src="${image.image_url}" loading="lazy">
      <div class="result-item-body">
        <div class="result-item-title">${resEscHtml(image.relation_label)} pair #${resEscHtml(image.pair_index)} — ${resEscHtml(image.role_label)}</div>
        <div class="response-cards">${responses}</div>
      </div>
    </div>
  `;
}

async function load() {
  const [schema, results] = await Promise.all([
    fetch("/api/annotate/schema").then(r => r.json()),
    fetch("/api/annotate/results").then(r => r.json()),
  ]);
  const labelByKey = Object.fromEntries(schema.fields.map(f => [f.key, f.label]));

  renderRatersSummary(results.raters);

  const scored = results.images.filter(img => img.responses.length > 0);
  document.getElementById("results-empty").classList.toggle("hidden", scored.length > 0);
  document.getElementById("results-list").innerHTML = scored.map(img => renderImage(img, labelByKey)).join("");
}

document.addEventListener("DOMContentLoaded", load);
