"""CLI orchestrator.

Usage:
    python -m src.pipeline run
    python -m src.pipeline run --stage search_images
    python -m src.pipeline run --subjects gwyneth_paltrow
    python -m src.pipeline run --limit-images 1 --stage search_images --subjects gwyneth_paltrow
    python -m src.pipeline run --force
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

import yaml
from dotenv import load_dotenv

# Import submodules so their @register decorators run.
from . import filters, search_backends, stages  # noqa: F401
from .registry import get as registry_get
from .stages.base import PipelineContext
from .state import ProgressState


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def build_context(config: dict, args: argparse.Namespace) -> PipelineContext:
    limits = dict(config.get("limits") or {})
    if args.subjects:
        limits["subjects"] = args.subjects
    if args.limit_subjects is not None:
        limits["subjects"] = args.limit_subjects
    if args.limit_images is not None:
        limits["images_per_type"] = args.limit_images

    return PipelineContext(subjects=[], limits=limits, config=config, state=ProgressState(), force=args.force)


def run_stages(ctx: PipelineContext, stage_cfgs: list[dict], stage_names: list[str] | None = None) -> None:
    """Run load_subjects (always first), then the given stages (or all enabled
    stages if stage_names is None, or only those named in stage_names)."""
    cfg_by_name = {s["name"]: s for s in stage_cfgs}

    # Subject resolution is required by every other stage, so it always runs first
    # regardless of stage_names filtering (this also gives `--stage load_subjects` its
    # natural meaning: "just resolve/research subjects and stop").
    load_cfg = cfg_by_name.get("load_subjects", {"name": "load_subjects", "params": {}})
    load_stage = registry_get("stage", "load_subjects")(**load_cfg.get("params", {}))
    ctx.log("=== Running stage: load_subjects ===")
    load_stage.run(ctx)

    if stage_names:
        remaining = [s for s in stage_cfgs if s["name"] in stage_names and s["name"] != "load_subjects"]
    else:
        remaining = [s for s in stage_cfgs if s.get("enabled", True) and s["name"] != "load_subjects"]

    for stage_cfg in remaining:
        stage_cls = registry_get("stage", stage_cfg["name"])
        stage = stage_cls(**stage_cfg.get("params", {}))
        ctx.log(f"=== Running stage: {stage_cfg['name']} ===")
        stage.run(ctx)


def run_pipeline_for_subject(
    subject_id: str,
    log: Callable[[str], None] = print,
    force: bool = False,
    config_path: str = "config/pipeline.yaml",
    on_images: Callable[[str, str, list[dict]], None] | None = None,
) -> None:
    """Run all enabled pipeline stages restricted to a single subject. Used by the
    web app's "add subject" flow to research + fetch + filter + export on demand."""
    config = load_config(config_path)
    ctx = PipelineContext(
        subjects=[], limits={"subjects": [subject_id]}, config=config, state=ProgressState(), force=force, log=log,
        on_images=on_images,
    )
    run_stages(ctx, config.get("stages", []))


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    ctx = build_context(config, args)
    run_stages(ctx, config.get("stages", []), args.stage)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Aging-dataset scraper/labeler pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run pipeline stages")
    run_parser.add_argument("--config", default="config/pipeline.yaml")
    run_parser.add_argument("--stage", action="append", help="run only this stage (repeatable)")
    run_parser.add_argument("--subjects", nargs="+", help="restrict to these subject ids")
    run_parser.add_argument("--limit-subjects", type=int, help="restrict to the first N subjects")
    run_parser.add_argument("--limit-images", type=int, help="restrict to the first N images per photo_type")
    run_parser.add_argument("--force", action="store_true", help="ignore state/progress.json and redo")

    args = parser.parse_args(argv)
    if args.command == "run":
        run(args)


if __name__ == "__main__":
    main()
