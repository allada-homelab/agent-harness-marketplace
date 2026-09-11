#!/usr/bin/env python3
"""A `gh` stand-in for pr-flow tests. See Task 3 interfaces for the replay schema."""
import json
import os
import sys

argv = sys.argv[1:]
replay_path = os.environ.get("FAKE_GH_REPLAY")
replay = json.load(open(replay_path)) if replay_path and os.path.exists(replay_path) else {}
log = os.environ.get("FAKE_GH_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(argv) + "\n")


def save():
    if replay_path:
        json.dump(replay, open(replay_path, "w"))


if argv[:2] == ["pr", "view"]:
    views = replay.get("pr_view") or []
    if "--jq" in argv and ".url" in argv:
        url = replay.get("pr_url") or ""
        if not url:
            sys.exit(1)
        print(url)
        sys.exit(0)
    if "--json" in argv and "url,state" in argv:
        url = replay.get("pr_url") or ""
        if not url:
            sys.exit(1)
        print(json.dumps({"url": url, "state": replay.get("pr_state", "OPEN")}))
        sys.exit(0)
    if not views:
        sys.exit(1)
    cur = views[0] if len(views) == 1 else views.pop(0)
    save()
    if isinstance(cur, dict) and cur.get("__fail__"):
        print("boom", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(cur))
elif argv[:2] == ["pr", "create"]:
    print("https://github.com/o/r/pull/7")
elif argv[:2] == ["repo", "view"]:
    print("o r")
elif argv[:2] == ["api", "graphql"]:
    n = int(replay.get("threads_unresolved", 0))
    nodes = [{"isResolved": False}] * n + [{"isResolved": True}]
    print(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}}))
elif argv[:2] == ["run", "view"]:
    print("\n".join(f"LOG-FOR-{argv[2]} line {i}" for i in range(300)))
elif argv[:2] == ["pr", "merge"]:
    views = replay.get("pr_view") or []
    if views:
        views[-1]["state"] = "MERGED"
        replay["pr_view"] = [views[-1]]
        save()
elif argv[:2] == ["pr", "list"]:
    head = argv[argv.index("--head") + 1]
    print("1" if head in replay.get("merged_branches", []) else "0")
else:
    print(f"fake_gh: unhandled {argv}", file=sys.stderr)
    sys.exit(1)
