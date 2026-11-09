import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config
from .chain import release_short
from .render import COUNT_ORDER, COUNT_WORD

MAX_CELL_CHANGES = 8


def fetch(src, rel):
    if "://" in src:
        with urllib.request.urlopen(f"{src.rstrip('/')}/{rel}", timeout=30) as r:
            return json.load(r)
    with open(os.path.join(src, rel)) as f:
        return json.load(f)


def load(src):
    api = {"eips": fetch(src, "eips.json"), "changes": fetch(src, "changes.json"),
           "clients": {c: fetch(src, f"client/{c}.json") for c in config.CLIENTS}}
    try:
        api["status"] = fetch(src, "status.json")
    except (FileNotFoundError, urllib.error.URLError):
        api["status"] = None
    return api


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url, text):
    return f"<{url}|{escape(text)}>"


def utc(stamp, fmt="%Y-%m-%d %H:%M UTC"):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc).strftime(fmt)


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def eip_key(eip):
    return (int(eip) if eip.isdigit() else 0, eip)


def state(api):
    eips = api["eips"]
    pending = {f'{p["repo"]}#{p["number"]}' for p in api["changes"]["pending"]}
    return {
        "snapshot": eips["snapshot"],
        "newest_release": eips["newest_release"],
        "stages": {e["eip"]: (e["stage"] or ["?"])[0] for e in eips["eips"]},
        "cells": {c: {cell["eip"]: cell["headline"] for cell in api["clients"][c]["cells"]} for c in config.CLIENTS},
        "behind": {e["eip"]: e["eels_todo"]["head"] for e in eips["eips"]
                   if (e.get("eels_todo") or {}).get("kind") == "eels-update"},
        "pending": sorted(pending),
    }


def stage_line(stages, tested):
    counts = {}
    for s in stages.values():
        counts[s] = counts.get(s, 0) + 1
    order = [s for s in config.TRACKED_STAGES if s in counts] + sorted(s for s in counts if s not in config.TRACKED_STAGES)
    parts = ", ".join(f"{counts[s]} {s}" for s in order)
    return f"*EIPs*: {len(stages)} tracked: {parts}; {tested} with tests"


def client_lines(api, pages):
    lines = []
    for c in config.CLIENTS:
        cells = api["clients"][c]["cells"]
        counts = {}
        for cell in cells:
            counts[cell["headline"]] = counts.get(cell["headline"], 0) + 1
        parts = []
        for h in COUNT_ORDER + sorted(h for h in counts if h not in COUNT_ORDER):
            if h not in counts:
                continue
            part = f"{counts[h]} {COUNT_WORD.get(h, h)}"
            if h == "fail":
                part += " (" + ", ".join(link(pages[cell["eip"]], f'EIP-{cell["eip"]}')
                                         for cell in sorted(cells, key=lambda x: eip_key(x["eip"])) if cell["headline"] == "fail") + ")"
            parts.append(part)
        lines.append(f"• {config.CLIENT_LABEL[c]}: {' · '.join(parts) if parts else 'no cells'}")
    return lines


def stale_line(api, newest):
    out = []
    for c in config.CLIENTS:
        rels = {}
        for cell in api["clients"][c]["cells"]:
            if cell["headline"] == "stale-release":
                r = release_short(cell["links"]["run"].get("release"))
                rels[r] = rels.get(r, 0) + 1
        for r in sorted(rels):
            out.append(f"{config.CLIENT_LABEL[c]} on {r} ({plural(rels[r], 'EIP')})")
    body = "; ".join(out) if out else "none"
    return f"*Old test release* (newest {release_short(newest)}): {body}"


def behind_lines(api):
    rows = [e for e in api["eips"]["eips"] if (e.get("eels_todo") or {}).get("kind") == "eels-update"]
    if not rows:
        return ["*Spec newer than tests*: none"]
    lines = ["*Spec newer than tests*:"]
    for e in sorted(rows, key=lambda x: eip_key(x["eip"])):
        t = e["eels_todo"]
        lines.append(f'• {link(t["diff_url"], "EIP-" + e["eip"])}: {plural(t["behind"], "commit")}, '
                     f'newest {utc(t["head_date"], "%Y-%m-%d")} ({t["head"][:8]})')
    return lines


def pending_line(pending):
    by_repo = {}
    for p in pending:
        repo = p.split("#", 1)[0]
        by_repo[repo] = by_repo.get(repo, 0) + 1
    parts = ", ".join(f"{repo.split('/', 1)[-1]} {n}" for repo, n in sorted(by_repo.items()))
    return f"*Open spec PRs*: {len(pending)}" + (f" ({parts})" if parts else "") + f" · {link(config.SITE_ROOT + '/changes.html', 'list')}"


def week_lines(prev, now):
    if prev is None:
        return ["_Week-over-week starts with the next digest._"]
    lines = []
    if prev["newest_release"] != now["newest_release"]:
        lines.append(f'newest tests {release_short(prev["newest_release"])} → {release_short(now["newest_release"])}')
    for eip in sorted(set(prev["stages"]) | set(now["stages"]), key=eip_key):
        a, b = prev["stages"].get(eip), now["stages"].get(eip)
        if a is None:
            lines.append(f"EIP-{eip} added as {b}")
        elif b is None:
            lines.append(f"EIP-{eip} dropped (was {a})")
        elif a != b:
            lines.append(f"EIP-{eip} {a} → {b}")
    changed = []
    for c in config.CLIENTS:
        old, new = prev["cells"].get(c, {}), now["cells"].get(c, {})
        for eip in sorted(set(old) & set(new), key=eip_key):
            if old[eip] != new[eip]:
                changed.append(f"{config.CLIENT_LABEL[c]} EIP-{eip}: {COUNT_WORD.get(old[eip], old[eip])} → {COUNT_WORD.get(new[eip], new[eip])}")
    lines += changed[:MAX_CELL_CHANGES]
    if len(changed) > MAX_CELL_CHANGES:
        lines.append(f"and {len(changed) - MAX_CELL_CHANGES} more cell changes")
    for eip in sorted(set(prev["behind"]) | set(now["behind"]), key=eip_key):
        a, b = prev["behind"].get(eip), now["behind"].get(eip)
        if b and a != b:
            lines.append(f"EIP-{eip} spec moved past tests")
        elif a and not b:
            lines.append(f"EIP-{eip} tests caught up with spec")
    old_p, new_p = set(prev["pending"]), set(now["pending"])
    if old_p != new_p:
        lines.append(f"open spec PRs {len(old_p)} → {len(new_p)} (+{len(new_p - old_p)} opened, −{len(old_p - new_p)} merged or closed)")
    head = f'*Since last week* ({utc(prev["snapshot"], "%Y-%m-%d")})'
    if not lines:
        return [f"{head}: no changes"]
    return [f"{head}:"] + [f"• {line}" for line in lines]


def render(api, prev=None):
    now = state(api)
    eips = api["eips"]
    meta = eips.get("meta") or {}
    pages = {e["eip"]: e["page"] for e in eips["eips"]}
    tested = len({cell["eip"] for c in config.CLIENTS for cell in api["clients"][c]["cells"]})
    title = f'*{escape(meta.get("name", eips["fork"]))} weekly* · {link(config.SITE_ROOT + "/", "eipproof")}'
    lines = [f'{title} · snapshot {utc(eips["snapshot"])} · tests {release_short(eips["newest_release"])}']
    status = api.get("status")
    if status and status.get("source") == "snapshot":
        lines.append(f':warning: site shows the {utc(status["snapshot"])} snapshot, live data failed')
    lines.append(stage_line(now["stages"], tested))
    lines.append(f'*Clients vs {release_short(eips["newest_release"])}*:')
    lines += client_lines(api, pages)
    lines.append(stale_line(api, eips["newest_release"]))
    lines += behind_lines(api)
    lines.append(pending_line(now["pending"]))
    lines += week_lines(prev, now)
    return "\n".join(lines) + "\n"


def main(args):
    prev = None
    if args.prev and os.path.exists(args.prev):
        with open(args.prev) as f:
            prev = json.load(f)
    api = load(args.api)
    print(render(api, prev), end="")
    if args.state_out:
        with open(args.state_out, "w") as f:
            json.dump(state(api), f, indent=1, sort_keys=True)
            f.write("\n")
