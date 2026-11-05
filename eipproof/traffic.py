import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from . import config

STALE_DAYS = 2
KINDS = ("views", "clones")


def gh(path):
    return json.loads(subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout)


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(path, doc):
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")


def merge_days(old, raw, today):
    days = {d["date"]: d for d in old}
    for kind in KINDS:
        for row in raw[kind][kind]:
            day = row["timestamp"][:10]
            if day < today:
                entry = days.setdefault(day, {"date": day, **{k: {"count": 0, "uniques": 0} for k in KINDS}})
                entry[kind] = {"count": row["count"], "uniques": row["uniques"]}
    return [days[d] for d in sorted(days)]


def record(repo, root, get=gh, today=None):
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = f"repos/{repo}/traffic"
    raw = {k: get(f"{base}/{k}") for k in KINDS}
    referrers, paths = get(f"{base}/popular/referrers"), get(f"{base}/popular/paths")
    site = urlparse(config.SITE_ROOT).hostname
    out = os.path.join(root, "traffic")
    os.makedirs(out, exist_ok=True)
    daily = os.path.join(out, "daily.json")
    save(daily, merge_days(load(daily, []), raw, today))
    totals = {k: {"count": raw[k]["count"], "uniques": raw[k]["uniques"]} for k in KINDS}
    from_site = {"count": sum(r["count"] for r in referrers if r["referrer"] == site),
                 "uniques": sum(r["uniques"] for r in referrers if r["referrer"] == site)}
    save(os.path.join(out, "latest.json"), {**totals, "from_site": from_site, "referrers": referrers, "paths": paths, "window_days": 14})
    v, c = totals["views"], totals["clones"]
    save(os.path.join(out, "badge.json"), {"schemaVersion": 1, "label": "GitHub repo, 14d", "color": "blue",
                                           "message": f'{v["count"]} views, {v["uniques"]} unique, {c["count"]} clones, {today}'})
    return totals, from_site


def check(root, today=None):
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    badge = load(os.path.join(root, "traffic", "badge.json"), None)
    if badge is None:
        return "no traffic/badge.json on the data branch: the repo traffic recorder has not run"
    day = badge["message"].rsplit(", ", 1)[-1]
    age = (date.fromisoformat(today) - date.fromisoformat(day)).days
    return f"repo traffic is {age} days old (last {day}): the recorder on the host stopped" if age > STALE_DAYS else ""


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["check"]:
        warn = check(argv[1])
        if warn:
            print(f"::warning title=repo traffic::{warn}")
        return 0
    totals, from_site = record(argv[0], argv[1])
    print(f'views {totals["views"]["count"]} ({totals["views"]["uniques"]} unique), clones {totals["clones"]["count"]}, from site {from_site["count"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
