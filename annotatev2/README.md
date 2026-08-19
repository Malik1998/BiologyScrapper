# annotatev2 — photo collection app

Step 1 from Medha's 2026-08-14 email: a simple web app where one family
sits down once and uploads 4 photos — reusing the exact photo-type
taxonomy already established in [`../Scrapping`](../Scrapping)'s
`src/models.py` (`PHOTO_TYPES`, minus the group-photo type, which isn't
needed here):

| photo_type      | who                          |
| ---------------- | ----------------------------- |
| `self_30_40`     | the subject, current photo    |
| `self_50_60`     | the subject, an older photo   |
| `mother_50_60`   | the subject's mother          |
| `father_50_60`   | the subject's father          |

Both `self_*` photos are required; `mother_50_60`/`father_50_60` are each
individually optional but **at least one of the two** is required (see
`OPTIONAL_GROUP` in `web/config.py`) — e.g. only one parent is
available/willing, that's fine. It doesn't matter who physically operates
the app — one person just picks 4 photos from their camera roll / files
and uploads them, no camera capture, no per-person sessions.

Sibling to `../Scrapping` (which has the `/annotate` FLR manual-scoring
tool, Step 2 of the same email) but a separate project — this one collects
fresh photos from real families instead of curating scraped ones, so it
doesn't share Scrapping's pipeline/dataset code, though it follows the same
conventions (FastAPI, Jinja2, plain JS, JSON-file storage under `data/`, no
database).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Defaults in `.env.example` work out of the box for local testing: no admin
password (admin pages 404), face check off, remote storage off (photos
stay local-only). Fill in `.env` before sending this to real participants —
see "Admin dashboard" and "Remote storage" below.

## Running

```bash
.venv/bin/uvicorn web.app:app --host 0.0.0.0 --port 8001
```

Open `http://127.0.0.1:8001/` — that's the upload page. Plain file
inputs (no camera), so no HTTPS requirement for local testing; if you send
this to remote families over plain HTTP that's fine too — only a live
camera would need HTTPS.

## The upload flow

One page: a family name field, then 4 photo cards
(`config/photo_types.json` — edit that file to change labels/requirements,
no code changes needed). For each card:

1. Pick a file (phone gallery or desktop file picker).
2. A crop box appears (defaults to the whole image) — drag/resize to frame
   the photo, then confirm.
3. **The full, uncropped photo is what gets stored** — the crop is saved as
   JSON (`{x, y, width, height}` in the original photo's pixel coordinates)
   alongside it, not baked into a second file. `GET
   /admin/photo/<id>/cropped` reconstructs the crop on demand from the two,
   which is also how you'd regenerate it later with different crop
   coordinates if needed.

Re-uploading a slot replaces the previous photo for it. A status line
tracks completeness (both self photos + at least one parent). Progress is
kept in `sessionStorage` + confirmed against the server (`GET
/api/submissions/<id>/photos`), so refreshing mid-upload doesn't lose
already-uploaded photos (though the browser-side thumbnail is gone until
you check `/admin`).

## Data layout

No database — one JSON file per record, matching `../Scrapping`'s
`annotate_data.py` approach (fine at this scale: a few dozen families,
~150 photos; every write touches its own file, so concurrent uploads never
contend with each other).

```
data/
  submissions/<submission_id>.json     # family_label, created_at
  photos/<photo_id>.json               # photo_type, crop, face_check, sync_status, ...
  photos/files/<photo_id>.jpg          # the full photo, EXIF-orientation-corrected
```

## Admin dashboard

`/admin` — lists every submission with its 4 photo thumbnails (rendered
through the crop-JSON reconstruction) and sync status.

**Wide open by default** (no login) as long as `ADMIN_USER`/`ADMIN_PASSWORD`
in `.env` are blank - a deliberate backdoor so you can eyeball uploads
during local testing without any setup. The page itself shows a warning
banner while it's in this state. **Before this ever holds a real
participant's face, set both env vars** - then `/admin` requires HTTP Basic
auth (wrong/missing credentials get a `401`).

## Handling load

Each request writes only its own files (no shared index to contend on),
and file writes / image processing / remote uploads all run off the event
loop (`asyncio.to_thread`), so one slow upload doesn't stall others. Photos
are always written to local disk synchronously first — fast and can't be
lost to a flaky remote — before anything is mirrored elsewhere.

## Remote storage (Yandex Disk / Cloudflare R2 / S3)

Both backends are fully implemented already — turning one on later is just
env vars, no code changes:

```bash
# .env
REMOTE_STORAGE_BACKEND=yandex_disk   # or: s3   (unset/none = local-only)
YANDEX_DISK_TOKEN=...                 # OAuth token, disk.write scope
# or for s3 / Cloudflare R2 (R2 speaks the S3 API):
S3_BUCKET=...
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com   # blank = real AWS S3
S3_REGION=auto                        # or an AWS region for real S3
```

A local copy is *always* kept regardless of this setting — remote storage
only ever gets a mirror. When enabled, each upload schedules a background
sync right away; a sweep loop (`web/sync_worker.py`, every 60s) retries
anything still `pending`/`failed` — e.g. the remote was briefly down, or
the process restarted mid-upload — so a transient failure can't silently
leave a photo unmirrored.

## Face check (optional, **off by default**)

`ENABLE_FACE_CHECK=true` rejects an upload with `422` unless OpenCV's
bundled Haar cascade finds exactly one face — an instant "please choose a
different photo" instead of finding out later. It's off by default because
it's extra CPU per upload that a small server may not want, and —
importantly — the `opencv-python-headless` dependency is **not required at
all** unless you turn this on: `web/face_check.py` imports `cv2` lazily,
and if it's missing the check just logs a warning and passes every photo
through rather than crashing the endpoint.

```bash
.venv/bin/pip install "opencv-python-headless>=4.9,<5"
```

Pin `<5`: verified during testing (2026-08) that `opencv-python-headless`
5.0's wheel dropped `cv2.CascadeClassifier` from the Python bindings
entirely (`AttributeError: module 'cv2' has no attribute
'CascadeClassifier'`) — this feature depends on it, so a 5.x install breaks
it. 4.x has it.

## Manual testing done

Ran the server locally end-to-end via `curl`: submission creation, photo
upload + resume tracking, slot-replace-on-reupload, crop-JSON round-trip
(uploaded with an arbitrary crop rect, confirmed
`/admin/photo/<id>/cropped` returns exactly that sub-rectangle), admin auth
(404 unconfigured / 401 wrong creds / 200 right creds), face check
(rejects a face-less image with 422, accepts a real face, degrades to
pass-through with a warning when `opencv` isn't installed), and both
remote backends' "not configured" error paths.

**Not tested**: the in-browser upload/crop UI (`web/static/app.js`) itself
— worth a manual run-through on a phone before sending this to families,
especially the crop-box drag/resize on a touchscreen and a tall portrait
photo's crop math (the CSS was written to keep the displayed image's
`clientWidth`/`clientHeight` equal to its actual rendered size — no
letterboxing — so the crop coordinates map back to pixels correctly; worth
double-checking on a real device).
