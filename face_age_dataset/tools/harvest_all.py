"""Build many people in parallel, resumable, with one shared Commons rate limit.

Threads rather than processes on purpose: the Commons throttle in commons.api
is a module global, so a single process keeps every worker under one polite
request rate. Processes would each get their own budget and hammer the API.
"""

import argparse
import glob
import json
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
import commons as C
from build import build_person, DATA

STATE = os.path.join(os.path.dirname(__file__), "..", "work", "harvest_state.json")
_lock = threading.Lock()


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    return {}


def save_state(st):
    with _lock:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)


def sync_state_from_dataset(state, overwrite=False):
    """Rebuild progress from the dataset itself.

    The state file is a convenience; the built folders are the truth. Without
    this, copying the project to another machine silently re-harvests everyone
    whose meta.json predates the state file -- which is exactly what happened
    to the first three people built here.
    """
    if not os.path.isdir(DATA):
        return state
    for slug in os.listdir(DATA):
        mp = os.path.join(DATA, slug, "meta.json")
        if not os.path.isfile(mp):
            continue
        try:
            m = json.load(open(mp))
        except Exception:
            continue
        rec = {"status": "ok" if m.get("complete_slots") else "empty",
               "slug": m.get("slug", slug),
               "complete_slots": m.get("complete_slots", 0),
               "has_minimum_set": m.get("has_minimum_set", False)}
        # index under every name that could be used to ask for this person
        for key in {m.get("query_name"), (m.get("subject") or {}).get("name")}:
            # overwrite: the dataset changed under the state file, e.g. review
            # removed picks, so "4 slots" in the state is no longer true
            if key and (overwrite or key not in state):
                state[key] = rec
    return state


def already_done(slug_guess, name, state):
    rec = state.get(name)
    return bool(rec and rec.get("status") in ("ok", "empty"))


def one(name, state, top, spec=None):
    spec = spec or {}
    try:
        meta = build_person(name, slug=spec.get("slug"), top=top, qid=spec.get("qid"),
                            father_qid=spec.get("father_qid"),
                            mother_qid=spec.get("mother_qid"),
                            web_slots=spec.get("web_slots"))
        if not meta:
            return name, {"status": "unresolved"}
        return name, {
            "status": "ok" if meta.get("complete_slots") else "empty",
            "slug": meta["slug"],
            "complete_slots": meta.get("complete_slots", 0),
            "has_minimum_set": meta.get("has_minimum_set", False),
        }
    except C.RateLimited as e:
        # not a failure of this person: harvest_all requeues them at the back
        print(f"  !! {name}: {e}", flush=True)
        return name, {"status": "rate_limited", "error": str(e)}
    except Exception as e:
        traceback.print_exc()
        return name, {"status": "error", "error": f"{type(e).__name__}: {e}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="people to build; default = seed list")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--top", type=int, default=60,
                    help="candidates scored per slot")
    ap.add_argument("--gap", type=float, default=None,
                    help="min seconds between Commons calls (shared)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", action="store_true", help="ignore saved state")
    ap.add_argument("--no-web", action="store_true",
                    help="do not fall back to web image search")
    ap.add_argument("--retry-missing", action="store_true",
                    help="re-run everyone without all 4 slots; filled slots are kept")
    ap.add_argument("--candidates", metavar="JSON",
                    help="also build people from candidates.py output (best first)")
    ap.add_argument("--fill-one-short", action="store_true",
                    help="only people one photo short of a minimum set; web search "
                         "only for that missing slot")
    ap.add_argument("--only-new", action="store_true",
                    help="with --candidates: skip the seed list")
    ap.add_argument("--max-new", type=int, default=0,
                    help="with --candidates: take at most this many new people")
    ap.add_argument("--web-cache", metavar="JSON",
                    help="answer web searches from this file (filled in a browser by "
                         "browser_bridge.py) instead of ddgs; unanswered queries go "
                         "to work/browser_queries.json")
    ap.add_argument("--all-missing", action="store_true",
                    help="everyone in dataset/ with an empty slot, pinned to the "
                         "Wikidata ids recorded in their meta.json")
    ap.add_argument("--requalify", action="store_true",
                    help="with --all-missing: also redo filled slots whose photo fails "
                         "the rating checks, keeping the old photo unless a better one passes")
    ap.add_argument("--strict-ages", action="store_true",
                    help="admit a photo only if both ends of its age range are in the window")
    ap.add_argument("--web-gap", type=float, default=0,
                    help="min seconds between web searches (default websearch.GAP)")
    args = ap.parse_args()

    seed = json.load(open(os.path.join(os.path.dirname(__file__), "seed_people.json")))
    specs = {p["name"]: p for p in seed["people"]}
    names = args.names or [p["name"] for p in seed["people"]]
    if args.fill_one_short:
        names = []
        for mp in sorted(glob.glob(os.path.join(DATA, "*", "meta.json"))):
            m = json.load(open(mp))
            if m.get("has_minimum_set"):
                continue
            sl = m["slots"]
            ok = lambda k: sl.get(k, {}).get("status") == "ok"
            have = {"subject_now": ok("subject_now"), "subject_young": ok("subject_young"),
                    "parent": ok("father_40s") or ok("mother_40s")}
            if sum(have.values()) != 2:
                continue
            miss = [k for k, v in have.items() if not v][0]
            web = {"father_40s", "mother_40s"} if miss == "parent" else {miss}
            nm = m.get("query_name") or m["subject"]["name"]
            specs[nm] = {"name": nm, "qid": m["subject"]["qid"],
                         "father_qid": (m.get("father") or {}).get("qid"),
                         "mother_qid": (m.get("mother") or {}).get("qid"),
                         "web_slots": web}
            names.append(nm)
        if args.names:
            names = [n for n in names if n in args.names]
        print(f"{len(names)} people one photo short of a minimum set", flush=True)
    if args.all_missing:
        names = []
        for mp in sorted(glob.glob(os.path.join(DATA, "*", "meta.json"))):
            m = json.load(open(mp))
            if all(e.get("status") == "ok" and (not args.requalify
                   or (e.get("qc") or {}).get("ok_for_rating", True) or e.get("source") == "web")
                   for e in m["slots"].values()):
                continue
            nm = m.get("query_name") or m["subject"]["name"]
            specs[nm] = {"name": nm, "qid": m["subject"]["qid"], "slug": m["slug"],
                         "father_qid": (m.get("father") or {}).get("qid"),
                         "mother_qid": (m.get("mother") or {}).get("qid")}
            names.append(nm)
        if args.names:
            names = [n for n in names if n in args.names]
        print(f"{len(names)} people with an empty slot", flush=True)
    if args.candidates and args.only_new:
        names = list(args.names)
    if args.candidates:
        # skip anyone already built or seeded, whatever name they were asked by
        known = {p.get("qid") for p in seed["people"]}
        for mp in glob.glob(os.path.join(DATA, "*", "meta.json")):
            known.add((json.load(open(mp)).get("subject") or {}).get("qid"))
        new = [c for c in json.load(open(args.candidates)) if c["qid"] not in known]
        if args.max_new:
            new = new[:args.max_new]
        for c in new:
            specs[c["name"]] = {"name": c["name"], "qid": c["qid"],
                                "father_qid": (c.get("father") or {}).get("qid"),
                                "mother_qid": (c.get("mother") or {}).get("qid")}
            names.append(c["name"])
        print(f"+{len(new)} new people from {args.candidates}", flush=True)
    if args.limit:
        names = names[:args.limit]

    # The Commons throttle is process-wide, so it must NOT scale with worker
    # count -- doing that lowers total request rate instead of raising it.
    # Threads win here by overlapping downloads and face detection, which do
    # not touch the throttled API at all.
    C.MIN_GAP = args.gap if args.gap else 1.0
    import build
    build.USE_WEB = not args.no_web
    build.STRICT_AGES = args.strict_ages
    build.REQUALIFY = args.requalify
    if args.web_gap:
        import websearch
        websearch.GAP = args.web_gap
    if args.web_cache:
        import websearch
        websearch.CACHE = json.load(open(args.web_cache)) if os.path.exists(args.web_cache) else {}
        websearch.RECORD = set()

    state = {} if args.redo else sync_state_from_dataset(load_state(),
                                                         overwrite=args.retry_missing)
    if not args.redo:
        save_state(state)
    if args.fill_one_short or args.all_missing:
        todo = list(names)
    elif args.retry_missing:
        todo = [n for n in names
                if (state.get(n) or {}).get("complete_slots", 0) < 4]
    else:
        todo = [n for n in names if args.redo or not already_done(None, n, state)]
    print(f"{len(todo)} to build ({len(names) - len(todo)} already done), "
          f"jobs={args.jobs} gap={C.MIN_GAP:.2f}s top={args.top}", flush=True)

    done = 0
    # A person refused by Wikimedia goes to the back of the queue (the pool
    # runs submissions in order) and is tried again once the others are done,
    # up to MAX_REQUEUE times; only then is it recorded as an error.
    MAX_REQUEUE = 3
    tries = {n: 0 for n in todo}
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        pending = {ex.submit(one, n, state, args.top, specs.get(n)) for n in todo}
        while pending:
            fut = next(as_completed(pending))
            pending.discard(fut)
            name, rec = fut.result()
            if rec.get("status") == "rate_limited":
                tries[name] += 1
                if tries[name] <= MAX_REQUEUE:
                    print(f"  -> {name}: requeued ({tries[name]}/{MAX_REQUEUE})", flush=True)
                    pending.add(ex.submit(one, name, state, args.top, specs.get(name)))
                    continue
                rec["status"] = "error"
            state[name] = rec
            save_state(state)
            done += 1
            print(f"[{done}/{len(todo)}] {name}: {rec.get('status')} "
                  f"slots={rec.get('complete_slots', '-')} "
                  f"min_set={rec.get('has_minimum_set', '-')}", flush=True)

    # a person is indexed under several names, so count distinct slugs
    uniq = {r.get("slug") or k: r for k, r in state.items()}
    ok = sum(1 for r in uniq.values() if r.get("status") == "ok")
    full = sum(1 for r in uniq.values() if r.get("complete_slots") == 4)
    mins = sum(1 for r in uniq.values() if r.get("has_minimum_set"))
    print(f"\ndone: {ok} built, {full} with all 4 slots, {mins} with the minimum set")
    print(f"dataset -> {os.path.abspath(DATA)}")
    if args.web_cache:
        import websearch
        qp = os.path.join(os.path.dirname(__file__), "..", "work", "browser_queries.json")
        json.dump(sorted(websearch.RECORD), open(qp, "w"), ensure_ascii=False, indent=0)
        print(f"{len(websearch.RECORD)} web queries still to run in the browser -> {qp}")


if __name__ == "__main__":
    main()
