# Aging dataset scraper / labeler

Builds a small labeled image dataset for an aesthetic "predict aging" product.
For each subject we need 4 photos:

| photo_type     | who                                  |
| -------------- | ------------------------------------- |
| `self_50_60`   | the subject, aged 50-60                |
| `self_30_40`   | the subject, aged 30-40                |
| `mother_50_60` | the subject's mother, aged 50-60       |
| `father_50_60` | the subject's father, aged 50-60       |

The pipeline searches the web for candidate photos, downloads and filters
them, and writes everything to a local `data/` folder. A FastAPI app lets a
non-programmer browse the candidates, pick/crop the final photos, and export
them.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in OPENROUTER_API_KEY (optional but recommended)
```

`OPENROUTER_API_KEY` enables:
- the `llm_align` / `vlm_verify` filters (text/vision relevance & identity checks)
- search-grounded identity research (birth years, parent names) for new subjects

Without it, the pipeline still runs end-to-end using the free DuckDuckGo
search backend and the heuristic filter only.

## Directory layout

```
config/
  celebrities.json   # source of truth: subjects, birth/death years, parents
  names.txt          # plain list of names -> regenerate celebrities.json from this
  pipeline.yaml      # stage list, filter chain, limits

src/                 # pipeline code (stages, filters, search backends, models)
web/                 # FastAPI review app
scripts/             # one-off CLI scripts (build_celebrities_config)

data/                # generated, gitignored
  subjects/<id>.json           # resolved subject + computed year-ranges
  raw/<id>/<photo_type>/        # downloaded candidates + .json sidecars
  selected/<id>/<photo_type>/   # final picks (after filter_chain / export_local)
  review/index.html             # static review gallery

state/progress.json # generated, gitignored - tracks completed (subject, photo_type, stage)
```

## Running the pipeline (CLI)

```bash
# everything, for all subjects in config/celebrities.json
.venv/bin/python -m src.pipeline run

# a single stage
.venv/bin/python -m src.pipeline run --stage search_images

# restrict to one subject
.venv/bin/python -m src.pipeline run --subjects gwyneth_paltrow

# cheapest possible smoke test: 1 subject, 1 image per slot, no filtering/LLM calls
.venv/bin/python -m src.pipeline run --limit-images 1 --stage search_images --subjects gwyneth_paltrow

# ignore state/progress.json and redo everything
.venv/bin/python -m src.pipeline run --force
```

Stages (defined in `config/pipeline.yaml`, run in order):

1. **load_subjects** - reads `config/celebrities.json`, computes target
   year-ranges per photo_type, writes `data/subjects/<id>.json`. Always runs
   first. If `research_unknown_parents: true`, also fills in low-confidence
   parent names via search-grounded LLM lookup.
2. **search_images** - for each (subject, photo_type), builds a search query
   and downloads candidate images + metadata sidecars into `data/raw/`.
   Pluggable search backend (`duckduckgo` by default; `serpapi`/`bing` need
   API keys).
3. **filter_chain** - runs an ordered, configurable chain of filters
   (`heuristic` always on; `llm_align`, `vlm_verify` optional, need
   `OPENROUTER_API_KEY`) and marks the top `top_k` candidates per slot as
   `selected`.
4. **export_local** - copies `selected` images into `data/selected/`.
5. **generate_html** - renders `data/review/index.html`, a static gallery for
   human review.

Everything is config-driven and pluggable: new search backends, filters, or
stages just need a `@register(...)` decorator (see `src/registry.py`) and an
entry in `pipeline.yaml`.

## Review / labeling web app

```bash
.venv/bin/uvicorn web.app:app --reload
```

Open http://127.0.0.1:8000/. From there you can:

- see per-subject/photo_type counts of selected vs. downloaded candidates
- open a subject to browse all candidates, select/deselect the final picks,
  crop images (via Cropper.js), and reset crops
- **Add new subject** (`/add`): type a name, and the app will research it
  (search-grounded birth year/parents lookup), add it to
  `config/celebrities.json`, then run `search_images -> filter_chain ->
  export_local -> generate_html` for just that subject - streaming progress
  live. When done you're linked to that subject's review page.
- export: ZIP of selected (cropped) photos, save to `data/selected/`, or
  regenerate `data/review/index.html`

## Regenerating `config/celebrities.json` from a name list

```bash
.venv/bin/python -m scripts.build_celebrities_config            # uses config/names.txt
.venv/bin/python -m scripts.build_celebrities_config --names "Tom Hanks" "Meryl Streep"
.venv/bin/python -m scripts.build_celebrities_config --overwrite  # re-research existing entries
```

For each name, this runs a few DuckDuckGo web searches and asks an LLM (via
OpenRouter) to extract birth year, category, and parent identities *from those
search results* (`src/research.py`) - grounding the answer in real sources
instead of relying on the model's memory. Requires `OPENROUTER_API_KEY`.
Existing entries are kept as-is unless `--overwrite` is passed.
# BiologyScrapper
