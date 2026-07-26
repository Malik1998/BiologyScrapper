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

## LLM telemetry

Every OpenRouter call (`src/llm/openrouter_client.py`) already logs to the
standard `logging` module: model, prompt size, latency, and token usage on
success; full traceback on failure. Control verbosity with `LOG_LEVEL` in
`.env` (`DEBUG`/`INFO`/`WARNING`, default `INFO`).

For a richer view (searchable traces, cost per subject, prompt diffing) you
can additionally point the pipeline at a self-hosted
[Langfuse](https://langfuse.com/) instance - MIT-licensed, no usage limits
when self-hosted:

```bash
# 1. run Langfuse locally (separate from this repo)
git clone https://github.com/langfuse/langfuse
cd langfuse && docker compose up -d   # -> http://localhost:3000

# 2. in the Langfuse UI: create an org/project, copy the public/secret keys

# 3. back in this repo's .env
pip install langfuse   # optional - only needed for tracing
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
```

If `langfuse` isn't installed, or the two keys aren't set, tracing is
silently disabled and the pipeline behaves exactly as before - this is the
same opt-in pattern as `OPENROUTER_API_KEY`. Image bytes are never sent to
Langfuse (redacted to `<elided>` in the trace input) to keep traces small.

**Known self-host issues (as of mid-2026)**, both in the Langfuse checkout's
`docker-compose.yml`, not in this repo. Try `git pull` in that checkout first
in case they've since been patched upstream.

- `pull access denied for cgr.dev/chainguard/minio` - their default minio
  image is currently ungated for anonymous pulls
  ([langfuse#11090](https://github.com/langfuse/langfuse/issues/11090),
  [langfuse#10488](https://github.com/langfuse/langfuse/issues/10488)). Fix:
  change the `minio` service's `image:` line to a pinned Docker Hub tag, e.g.
  `minio/minio:RELEASE.2024-11-07T00-52-20Z`, keeping its
  `command`/`environment`/`volumes` as-is.
- `failed to bind host port for 127.0.0.1:6379 ... address already in use` -
  something else on the machine already has Redis's default port. Check with
  `sudo lsof -i :6379`, then remap the `redis` service's `ports:` entry to a
  free host port, e.g. `"127.0.0.1:6380:6379"` (only the host side, left of
  the colon, needs to change - Langfuse's own containers talk to Redis over
  the internal Docker network by service name, not the published port).

### OpenRouter blocked with "Access denied by security policy"

If every OpenRouter call fails with a `403` and body
`{"success": false, "error": "Access denied by security policy."}`, check the
response headers for `server: cloudflare` - that means the request is being
rejected at OpenRouter's edge/WAF before it reaches their app (confirmed by
this failing identically across different models, so it isn't a
model/provider access issue). In practice this has been observed for
servers hosted on Russian networks, regardless of which model is requested.

The fix is routing OpenRouter requests through a different exit IP. Two
options, either works - only `src/llm/openrouter_client.py` is affected, the
DuckDuckGo/Wikipedia/etc. search backends are unaffected either way:

**Option A - your own relay (`relay/app.py`)**, if you have a second server
that *can* reach OpenRouter directly. It's a tiny transparent forwarder: it
never sees or stores an API key of its own, it just passes through whatever
`Authorization` header the caller sends.

```bash
# on the non-blocked server:
pip install fastapi "uvicorn[standard]" requests
uvicorn relay.app:app --host 0.0.0.0 --port 8787

# in .env on the blocked machine (this repo):
OPENROUTER_BASE_URL=http://<relay-host>:8787
```
`OPENROUTER_API_KEY` still only ever lives in `.env` on the blocked
machine - the relay just relays it through, request by request. The relay
has no auth of its own, so put it behind a firewall rule that only allows
your blocked server's IP - don't leave it open on the public internet.

**Option B - a generic proxy.** Set `OPENROUTER_PROXY_URL` in `.env` to an
HTTP(S) or SOCKS proxy reachable from the pipeline's host, e.g.:
```bash
OPENROUTER_PROXY_URL=http://user:pass@some-non-blocked-host:8080
# or, for a SOCKS5 proxy (e.g. `ssh -D 1080 user@non-blocked-host`):
OPENROUTER_PROXY_URL=socks5h://127.0.0.1:1080
```
SOCKS proxies need `pip install "requests[socks]"` in addition to the base
requirements.

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

## How image selection works (algorithm details)

For each `(subject, photo_type)` slot, three phases run in sequence:

**1. Query building** (`src/models.py:Subject.year_range`, `src/stages/search_images.py`)
- The target year window is derived from birth/death years: e.g. `self_50_60`
  = birth_year+50 .. birth_year+60, clamped to the current year and (if
  applicable) death year. For parents with an unknown birth year, it's
  estimated as `subject.birth_year - 27`.
- The window is split into points every `year_step` years (default 3), and
  one query is built per point: `"{person_label} {year} photo"` (e.g.
  `"Meryl Streep 1975 photo"`).
- Each query is run through the configured search backend
  (`duckduckgo` by default - see `src/search_backends/`) requesting up to
  `max_results_per_query` results; each result is downloaded, deduped by
  content hash, and saved to `data/raw/<subject_id>/<photo_type>/` with a
  `.json` sidecar (title/description/page_url/query). No filtering or
  scoring happens in this phase - it's pure discovery.

**2. Filter chain** (`config/pipeline.yaml:filter_chain.chain`,
`src/stages/filter_chain.py`) - an ordered pipeline; each filter only sees
candidates the previous filter didn't already reject:
- `heuristic` (`src/filters/heuristic.py`, always on, no LLM) - rejects images
  below `min_width`/`min_height` (400x400 default) or with an aspect ratio
  above `max_aspect_ratio` (2.5).
- `llm_align` (`src/filters/llm_align.py`, **disabled by default**) - a
  **text-only LLM call**. Sends only the metadata (title/description/page
  URL, *not* the pixels) to an OpenRouter model (`google/gemini-2.5-flash` by
  default) and asks "how likely is this really that person around that
  year?", returning `{"relevance": 0-1}`. Cheap pre-filter before spending a
  vision call.
- `vlm_verify` (`src/filters/vlm_verify.py`, **disabled by default**) - a
  **vision LLM call**. Sends the actual downloaded image (base64) to an
  OpenRouter vision model and asks it to judge identity match, estimated
  age/year, whether a single face is clearly visible, and image quality,
  returning `{"verdict": 0-1, ...}`. This is the step that actually looks at
  pixels to confirm "is this the right person at the right age".
- Both LLM filters need `OPENROUTER_API_KEY`; without it they no-op (scores
  marked `"skipped"`, candidates pass through unscored). All OpenRouter calls
  go through `src/llm/openrouter_client.py` (`chat_text` / `chat_vision`),
  hitting `https://openrouter.ai/api/v1/chat/completions`.

**3. Ranking & selection** (`_score` / `_rank_and_select` in
`src/stages/filter_chain.py`)
- Score = average of `llm_align.relevance` and `vlm_verify.verdict` (whichever
  ran); `0.5` (neutral) if neither ran; a `heuristic`-rejected image is never
  selected regardless of score.
- Candidates are sorted by score descending, and the top `top_k` (default 4)
  are marked `status="selected"`; the rest stay `candidate` (still visible and
  manually pickable in the review app) unless `heuristic` marked them
  `filtered_out`. `export_local` then copies only `selected` images to
  `data/selected/`.

**In short:** out of the box (no `OPENROUTER_API_KEY`, default
`pipeline.yaml`), there's no relevance/identity signal at all - selection is
just "first `top_k` downloaded images per slot that pass the resolution/aspect
checks". Enabling `llm_align` and/or `vlm_verify` in `pipeline.yaml` (and
setting `OPENROUTER_API_KEY`) is what makes selection identity- and
age-aware.

A separate, unrelated use of the LLM is **identity research**
(`src/research.py`): given a person's name, it runs a few plain-text web
searches (DuckDuckGo) and asks the LLM to extract birth year / parents'
names *only from those search snippets* (grounded, not memory-based). This
powers `research_unknown_parents` in `load_subjects` and
`scripts/build_celebrities_config.py` / the web app's "Add new subject" flow
- it fills in *who to search for*, not which downloaded photo to pick.

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

## FLR reliability test (`/annotate`) - Step 2

Before spending real time/money on a bigger dataset, we first check whether
the [FLR scale](https://en.wikipedia.org/wiki/Facial_laxity) can even be
scored consistently by different people on real-world (non-standardized)
photos. Step 2 of that check: two (or more) team members independently score
the *same* small batch of photos, so we can measure whether they actually
agree (inter-rater reliability) before committing to FLR as our rubric. This
section covers that flow end to end - see `web/annotate_data.py` for the
implementation notes this summarizes.

### 1. Sample a batch from KinFaceW

```bash
.venv/bin/python -m scripts.build_kinface_ii_age_batch
```

This is `scripts/build_kinface_ii_age_batch.py`. What it does:

1. Reads the public [KinFaceW-II](https://www.kinfacew.com/download.html)
   dataset from `../KinFaceW-II` (one level above this repo - override with
   `--source`). KinFaceW-II only, not KinFaceW-I - see below for why.
   KinFaceW stores each parent-child pair as two files,
   `<code>_<pair_index>_1.jpg` (parent) and `..._2.jpg` (child), inside one
   folder per relation: `father-dau`, `father-son`, `mother-dau`, `mother-son`.
2. Reads child ages from
   `../kinface_age_estimation/results/kinfacew_children_age_estimation.csv`
   (a DeepFace age-estimation pass over just the child photo of each pair -
   see `kinface_age_estimation/run_age_estimation.py` - this is why only
   KinFaceW-II is in scope here: that's the dataset the csv covers).
   **Parents have no estimated age** - DeepFace was only run on the child
   photos. Age is only used to pick a balanced sample; it isn't stored in
   `batch.json` or shown anywhere in the annotation UI.
3. Samples `--count` pairs (default **50**) stratified evenly across the
   child's estimated age: pairs are grouped by integer age, then picked
   round-robin youngest-to-oldest so every age bucket contributes 1-2 pairs
   (capped by how many that age actually has) instead of the sample being
   dominated by the most common ages. `--seed` (default 42) makes it
   reproducible.
4. Copies just the sampled pairs into `data/kinface_photos/<relation>/...jpg`,
   preserving KinFaceW's own filenames/layout (so parent/child pairing is
   still recoverable later, e.g. for the Step 4 pilot).
5. Writes `data/annotations/batch.json`: the fixed, ordered list of those 100
   photos (one entry per *individual photo*, not per pair - FLR is scored per
   photo). This file **is the batch everyone annotates** - re-running the script without
   `--force` refuses to overwrite it, since reshuffling it after people have
   started would break the "same batch" guarantee. If you do need to
   resample, archive `data/annotations/{responses,raters.json,batch.json}`
   first (see `data/annotations/archive/` for an example) so nobody's
   completed work is silently invalidated - `--force` only overwrites
   `batch.json`, it won't do that archiving for you.

The older `scripts/build_kinface_batch.py` (KinFaceW-I, unstratified) still
works the same way if you ever want a plain random sample instead.

`data/` (including `data/kinface_photos` and `data/annotations`) is
gitignored, consistent with KinFaceW's non-redistribution terms of use -
images stay local, never pushed to git or the internet.

### 2. Score photos

```bash
.venv/bin/uvicorn web.app:app --reload
```

Open http://127.0.0.1:8000/annotate. Flow:

1. **Enter your name.** No auth - it's just used to track your personal
   progress through the batch (remembered in the browser via `localStorage`,
   and server-side by a slugified version of the name, e.g. "Medha" ->
   `medha`).
2. You're shown **one photo at a time** with a form pre-filled empty
   (`config/annotation_schema.json` - the same "edit config, not code" pattern
   as `config/image_meta_schema.json` used by the existing Meta modal): 4 FLR
   signs/regions (eyelid folds, nasojugal folds, jowls, neck profile), each a
   0-4 severity dropdown plus an explicit "NA - not scoreable in this photo"
   option, plus photo quality/angle tags. A "Form" / "JSON" toggle lets you
   edit the same values as raw JSON if that's faster. There's a separate free-text
   comments box below it.
3. **Submit & next photo** saves your scores to
   `data/annotations/responses/<your_slug>/<image_id>.json` and immediately
   serves your next unscored photo from the batch.
4. Because `batch.json` is the same fixed list for everyone, every rater who
   finishes it has scored the exact same 100 photos (50 pairs) - that's what
   makes the inter-rater comparison possible; no per-photo assignment/overlap
   logic is needed. `/annotate` just skips whatever *you* have already
   submitted, so you'll never be shown the same photo twice in the normal
   flow.
5. **"my scored photos"** (top of the page once you've scored at least one
   photo) lists everything you've submitted so far with a thumbnail and your
   saved scores/comment; **Edit** reopens that photo prefilled so you can fix
   a typo'd score without disturbing your place in the main queue - saving
   just overwrites that one response file and takes you back to the list.
6. `GET /api/annotate/team_progress` (JSON) shows, per photo, which raters
   have scored it yet and how many raters have finished overall - useful for
   knowing when there's enough overlap to actually compute agreement (e.g.
   weighted kappa) on.

### Data layout

```
data/kinface_photos/<relation>/<pair>_<1|2>.jpg   sampled KinFaceW photos
data/annotations/batch.json                       fixed list every rater works through
data/annotations/raters.json                      name slug -> display name
data/annotations/responses/<rater_slug>/<image_id with "/" -> "__">.json
                                                    one file per (rater, photo):
                                                    {rater, image_id, submitted_at, scores, comment}
data/annotations/archive/<...>/                    old batch+responses set aside when
                                                    the batch was last resampled from scratch
```

### Refining the rubric (Step 3)

`config/annotation_schema.json` is config, not code - to add/remove/reword a
scored field (e.g. once we know which FLR signs actually survive as
reliably-scoreable, per the "modified real-world-photo rubric" discussion),
just edit that file. No changes needed in `web/app.py` or `annotate.js`.
# BiologyScrapper
