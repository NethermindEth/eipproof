import json
import os
import sys
import time
import urllib.request

from . import config

PAGES = ["index.html", "queue.html", "changes.html", "eip-7906.html", "client-nethermind.html"]
HEADLINES = {"pass", "open", "fail", "stale-release", "no-run", "no-tests"}
CELL_KEYS = {"eip", "client", "headline", "text", "why", "links"}
DOC_KEYS = {"fork", "snapshot", "source", "newest_release", "listing_url", "cells", "todo"}
MIN_EIPS = 4


def http_fetch(base, bust):
    def get(path):
        with urllib.request.urlopen(urllib.request.Request(f"{base.rstrip('/')}/{path}?v={bust}", headers={"User-Agent": f"{config.NAME}/0.1"}), timeout=60) as r:
            return r.read().decode()
    return get


def check_doc(doc, where):
    errs = []
    if not isinstance(doc, dict):
        return [f"{where}: not an object"]
    missing = DOC_KEYS - doc.keys()
    if missing:
        errs.append(f"{where}: missing {sorted(missing)}")
    if doc.get("fork") != config.FORK:
        errs.append(f"{where}: fork {doc.get('fork')!r}")
    for i, c in enumerate(doc.get("cells") or []):
        if CELL_KEYS - c.keys():
            errs.append(f"{where}: cell {i} missing {sorted(CELL_KEYS - c.keys())}")
        elif c["headline"] not in HEADLINES:
            errs.append(f"{where}: cell {i} headline {c['headline']!r}")
    return errs


def check(get, commit=""):
    errs = []
    try:
        status = json.loads(get("api/status.json"))
    except Exception as e:
        return [f"api/status.json: {e}"]
    if commit and status.get("commit") != commit:
        return [f"api/status.json: commit {status.get('commit')!r}, want {commit!r}"]
    for p in PAGES:
        try:
            body = get(p)
        except Exception as e:
            errs.append(f"{p}: {e}")
            continue
        if not body.rstrip().endswith("</html>") or config.NAME not in body:
            errs.append(f"{p}: not a full {config.NAME} page")
        banner = 'id="fallback"' in body
        if banner != (status.get("source") == "snapshot"):
            errs.append(f"{p}: fallback banner {'shown' if banner else 'missing'} for source {status.get('source')!r}")
    cells = []
    for client in config.CLIENTS:
        try:
            doc = json.loads(get(f"api/client/{client}.json"))
        except Exception as e:
            errs.append(f"api/client/{client}.json: {e}")
            continue
        errs += check_doc(doc, f"api/client/{client}.json")
        cells += doc.get("cells") or []
    lo, hi = MIN_EIPS * len(config.CLIENTS), len(config.ROW_ORDER) * len(config.CLIENTS)
    if not lo <= len(cells) <= hi:
        errs.append(f"cells: {len(cells)} not in [{lo}, {hi}]")
    if status.get("cells") != len(cells):
        errs.append(f"cells: status says {status.get('cells')}, client JSON has {len(cells)}")
    try:
        if not json.loads(get("api/changes.json")).get("changes"):
            errs.append("api/changes.json: no changes")
    except Exception as e:
        errs.append(f"api/changes.json: {e}")
    try:
        doc = json.loads(get("api/eip/7906.json"))
        errs += check_doc(doc, "api/eip/7906.json")
        if not any(c.get("client") == "nethermind" and c.get("eip") == "7906" for c in doc.get("cells") or []):
            errs.append("api/eip/7906.json: no 7906 x nethermind cell")
    except Exception as e:
        errs.append(f"api/eip/7906.json: {e}")
    return errs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    base, commit = argv[0], argv[1] if len(argv) > 1 else ""
    remote = base.startswith(("http://", "https://"))
    for attempt in range(10 if remote else 1):
        get = http_fetch(base, f"{commit[:12]}-{attempt}") if remote else lambda p: open(os.path.join(base, p)).read()
        errs = check(get, commit)
        if not errs:
            print(f"smoke ok {base} {commit}")
            return 0
        if remote and attempt < 9:
            time.sleep(20)
    for e in errs:
        print(f"::error title=smoke::{e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
