"""Build many people in parallel, resumable, with one shared Commons rate limit.

Threads rather than processes on purpose: the Commons throttle in commons.api
is a module global, so a single process keeps every worker under one polite
request rate. Processes would each get their own budget and hammer the API.
"""

import argparse
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


def sync_state_from_dataset(state):
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
            if key and key not in state:
                state[key] = rec
    return state


def already_done(slug_guess, name, state):
    rec = state.get(name)
    return bool(rec and rec.get("status") in ("ok", "empty"))


def one(name, state, top):
    try:
        meta = build_person(name, top=top)
        if not meta:
            return name, {"status": "unresolved"}
        return name, {
            "status": "ok" if meta.get("complete_slots") else "empty",
            "slug": meta["slug"],
            "complete_slots": meta.get("complete_slots", 0),
            "has_minimum_set": meta.get("has_minimum_set", False),
        }
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
    args = ap.parse_args()

    names = args.names
    if not names:
        seed = json.load(open(os.path.join(os.path.dirname(__file__), "seed_people.json")))
        names = [p["name"] for p in seed["people"]]
    if args.limit:
        names = names[:args.limit]

    # The Commons throttle is process-wide, so it must NOT scale with worker
    # count -- doing that lowers total request rate instead of raising it.
    # Threads win here by overlapping downloads and face detection, which do
    # not touch the throttled API at all.
    C.MIN_GAP = args.gap if args.gap else 1.0

    state = {} if args.redo else sync_state_from_dataset(load_state())
    if not args.redo:
        save_state(state)
    todo = [n for n in names if args.redo or not already_done(None, n, state)]
    print(f"{len(todo)} to build ({len(names) - len(todo)} already done), "
          f"jobs={args.jobs} gap={C.MIN_GAP:.2f}s top={args.top}", flush=True)

    done = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(one, n, state, args.top): n for n in todo}
        for fut in as_completed(futs):
            name, rec = fut.result()
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


if __name__ == "__main__":
    main()
