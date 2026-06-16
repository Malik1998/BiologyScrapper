from __future__ import annotations

import html
import json
import os
from pathlib import Path

from ..registry import register
from .base import PipelineContext, Stage


@register("stage", "generate_html")
class GenerateHtmlStage(Stage):
    """Builds a single static review gallery HTML page grouped by subject -> photo_type,
    preferring data/selected (post filter_chain) and falling back to data/raw."""

    name = "generate_html"

    def run(self, ctx: PipelineContext) -> None:
        output = Path(self.params.get("output", "data/review/index.html"))
        selected_dir = Path("data/selected")
        raw_dir = Path("data/raw")

        sections = []
        for subject in ctx.iter_subjects():
            subject_blocks = []
            for photo_type in ctx.photo_types:
                source_dir = selected_dir / subject.id / photo_type
                if not source_dir.exists() or not any(source_dir.glob("*.json")):
                    source_dir = raw_dir / subject.id / photo_type
                if not source_dir.exists():
                    continue

                cards = [
                    _card(json.loads(sidecar.read_text()), output.parent)
                    for sidecar in sorted(source_dir.glob("*.json"))
                ]
                if cards:
                    subject_blocks.append(
                        f"<h3>{html.escape(photo_type)}</h3><div class='cards'>{''.join(cards)}</div>"
                    )

            if subject_blocks:
                sections.append(f"<section><h2>{html.escape(subject.name)}</h2>{''.join(subject_blocks)}</section>")

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_PAGE_TEMPLATE.format(sections="".join(sections)))
        ctx.log(f"[generate_html] wrote {output}")


def _card(data: dict, html_dir: Path) -> str:
    img_path = Path(data.get("cropped_path") or data["local_path"]).resolve()
    try:
        rel = os.path.relpath(img_path, html_dir)
    except ValueError:
        rel = str(img_path)

    score_lines = "".join(
        f"<div class='score'><b>{html.escape(key)}</b>: {html.escape(json.dumps(val))}</div>"
        for key, val in data.get("scores", {}).items()
    )
    status = data.get("status", "candidate")
    page_url = data.get("page_url", "")
    return (
        "<div class='card'>"
        f"<img src='{html.escape(rel)}' loading='lazy'>"
        "<div class='meta'>"
        f"<span class='status status-{html.escape(status)}'>{html.escape(status)}</span>"
        f"<div>{data.get('width', 0)}x{data.get('height', 0)}</div>"
        f"<a href='{html.escape(page_url)}' target='_blank'>source</a>"
        f"{score_lines}"
        "</div></div>"
    )


_PAGE_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Aging dataset review</title>
<style>
body {{ font-family: sans-serif; margin: 1.5rem; }}
section {{ margin-bottom: 2rem; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
.card {{ width: 220px; border: 1px solid #ddd; border-radius: 6px; padding: 0.5rem; }}
.card img {{ width: 100%; height: 220px; object-fit: cover; border-radius: 4px; }}
.meta {{ font-size: 0.8rem; margin-top: 0.4rem; }}
.score {{ word-break: break-all; color: #555; }}
.status {{ display: inline-block; padding: 0 6px; border-radius: 4px; color: white; font-weight: bold; }}
.status-selected {{ background: #2e7d32; }}
.status-candidate {{ background: #888; }}
.status-filtered_out {{ background: #c62828; }}
</style></head>
<body>
<h1>Aging dataset &mdash; review gallery</h1>
{sections}
</body></html>
"""
