from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..registry import register
from .base import PipelineContext, Stage


@register("stage", "export_local")
class ExportLocalStage(Stage):
    """Copies status="selected" images + sidecar metadata from data/raw into
    data/selected/<subject_id>/<photo_type>/, ready for human review/handoff."""

    name = "export_local"

    def run(self, ctx: PipelineContext) -> None:
        output_dir = Path(self.params.get("output_dir", "data/selected"))

        for subject in ctx.iter_subjects():
            for photo_type in ctx.photo_types:
                raw_dir = Path("data/raw") / subject.id / photo_type
                if not raw_dir.exists():
                    continue

                dest_dir = output_dir / subject.id / photo_type
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)

                count = 0
                for sidecar in sorted(raw_dir.glob("*.json")):
                    data = json.loads(sidecar.read_text())
                    if data.get("status") != "selected":
                        continue
                    src_img = Path(data.get("cropped_path") or data["local_path"])
                    if not src_img.exists():
                        continue
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_img, dest_dir / src_img.name)
                    shutil.copy2(sidecar, dest_dir / sidecar.name)
                    count += 1

                if count:
                    ctx.log(f"[export_local] {subject.id}/{photo_type}: exported {count} image(s) -> {dest_dir}")

        ctx.log(f"[export_local] done -> {output_dir}")
