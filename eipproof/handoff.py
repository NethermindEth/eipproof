import re
import time

from . import config, diverge, sources
from .chain import headline_text, release_short

BATCH = 3
GAP = 2.5
TRIES = 3
BACKOFF = 15


def title_mentions(title, eip):
    return re.search(rf"(?<![a-z0-9])eip[-_ ]?{eip}(?!\d)", title, re.I) is not None


def pr_row(item):
    merged = (item.get("pull_request") or {}).get("merged_at")
    return {"number": item["number"], "title": item["title"], "url": item["html_url"], "draft": bool(item.get("draft")),
            "created": item["created_at"][:10], "merged": merged, "state": "open" if item["state"] == "open" else "merged" if merged else "closed"}


def search(repo, batch, only_open):
    q = f"repo:{repo}+is:pr" + ("+is:open" if only_open else "") + "+in:title+" + "+OR+".join(t for eip in batch for t in (eip, f"eip{eip}"))
    err = None
    for i in range(TRIES):
        try:
            return sources.gh_api(f"search/issues?q={q}&per_page=100&sort=created&order=desc")
        except Exception as e:
            err = e
            if i + 1 < TRIES:
                time.sleep(BACKOFF * (i + 1))
    raise err


def collect_repo(repo, eips, only_open, gap):
    found, truncated = {}, False
    for start in range(0, len(eips), BATCH):
        batch = eips[start:start + BATCH]
        if start:
            time.sleep(gap)
        hits = search(repo, batch, only_open)
        items = [i for i in hits.get("items", []) if "pull_request" in i]
        truncated = truncated or hits.get("total_count", 0) > len(hits.get("items", []))
        for item in items:
            row = pr_row(item)
            if row["state"] == "closed":
                continue
            for eip in batch:
                if title_mentions(item["title"], eip) and all(p["number"] != row["number"] for p in found.get(eip, [])):
                    found.setdefault(eip, []).append(row)
    for rows in found.values():
        rows.sort(key=lambda p: (p["state"] != "open", -p["number"]))
    return {"repo": repo, "state": "ok", "truncated": truncated, "eips": found}


def collect(eips, log=print, gap=GAP):
    eips = sorted(eips)
    repos = [("eels", config.EELS_REPO, True)] + [(c, config.CLIENT_REPO[c], False) for c in config.CLIENTS]
    out = {}
    for n, (key, repo, only_open) in enumerate(repos):
        if n:
            time.sleep(gap)
        try:
            out[key] = collect_repo(repo, eips, only_open, gap)
            log(f"prs   {repo}: {sum(len(v) for v in out[key]['eips'].values())} PR link(s)" + (" (search truncated)" if out[key]["truncated"] else ""))
        except Exception as e:
            out[key] = {"repo": repo, "state": "unreachable", "reason": type(e).__name__, "eips": {}}
            log(f"::warning title=client PRs::{repo}: {type(e).__name__}")
    return out


def client_prs(snap, key, eip):
    linked = snap.get("linked_prs")
    if linked is None or key not in linked:
        return {"state": "not-collected", "repo": config.EELS_REPO if key == "eels" else config.CLIENT_REPO[key], "prs": []}
    block = linked[key]
    if block["state"] != "ok":
        return {"state": "unreachable", "repo": block["repo"], "reason": block.get("reason"), "prs": []}
    return {"state": "ok", "repo": block["repo"], "truncated": block.get("truncated", False), "prs": block["eips"].get(eip, [])}


def pending_spec(snap, eip):
    rows = [{"repo": config.EIPS_REPO, "number": p["number"], "title": p["title"], "url": p["url"]} for p in snap["eips"][eip].get("pending", [])]
    eels = client_prs(snap, "eels", eip)
    rows += [{"repo": config.EELS_REPO, "number": p["number"], "title": p["title"], "url": p["url"]} for p in eels["prs"] if p["state"] == "open"]
    return rows


def hints(snap, eip, client):
    rows = []
    for e in diverge.doc(snap)["eips"]:
        if e["eip"] != eip:
            continue
        for ref in e["refs"]:
            if ref["client"] != client:
                continue
            for name, c in ref["cells"].items():
                if c.get("url"):
                    rows.append({"name": name, "state": c["state"], "value": c.get("value"), "url": c["url"], "ref": ref.get("ref")})
    return {"state": "ok" if rows else "none", "rows": rows}


def brief(cell, snap, why_text):
    eip, client = cell["eip"], cell["client"]
    info = snap["eips"][eip]
    s, r = cell["links"]["spec"], cell["links"]["run"]
    changes = [{"commit": d["commit"], "date": d["date"], "subject": d["subject"], "url": f'{config.GITHUB}/{config.EIPS_REPO}/commit/{d["commit"]}',
                "constants": d.get("constants", [])} for d in info["deltas"]]
    return {
        "eip": eip, "client": client, "client_label": config.CLIENT_LABEL[client], "headline": cell["headline"], "text": headline_text(cell),
        "why": why_text, "fork": config.FORK, "snapshot": snap["taken_at"],
        "spec": {"head": info["head"], "head_url": f'{config.GITHUB}/{config.EIPS_REPO}/commit/{info["head"]}',
                 "text_url": f'{config.GITHUB}/{config.EIPS_REPO}/blob/{info["head"]}/{info["path"]}',
                 "pin_commit": s["pin_commit"], "behind": s["behind"], "changes": changes},
        "tests": {"state": r["state"], "release": r.get("release"), "newest_release": snap["newest_release"], "passed": r.get("passed"),
                  "total": r.get("total"), "failed": r.get("failed", []), "run_url": r.get("url"),
                  "test_dir_url": f'{config.GITHUB}/{config.EELS_REPO}/tree/{snap["newest_release"].replace("@", "%40")}/{info["test_dir"]}'},
        "client_prs": client_prs(snap, client, eip),
        "pending_spec": pending_spec(snap, eip),
        "hints": hints(snap, eip, client),
        "page": f'{config.SITE_URL}/index.html#{eip}-{client}',
    }


def md(url, text):
    return f"[{text}]({url})"


def pr_line(p):
    return f'- {md(p["url"], "#" + str(p["number"]))} {p["title"]} ({p["state"]}' + (", draft" if p.get("draft") else "") + ")"


def brief_markdown(doc):
    s, t, c = doc["spec"], doc["tests"], doc["client_prs"]
    lines = [f'**Implement EIP-{doc["eip"]} in {doc["client_label"]}** ({doc["text"]}, fork {doc["fork"]}, snapshot {doc["snapshot"]})', "",
             doc["why"], "", f'Spec: {md(s["text_url"], "EIP text at " + s["head"][:8])}']
    for ch in s["changes"]:
        consts = "; ".join(f'`{k["name"]}` {", ".join(k["before"]) or "-"} -> {", ".join(k["after"]) or "-"}' for k in ch["constants"])
        lines.append(f'- {md(ch["url"], ch["commit"][:8])} {ch["date"][:10]} {ch["subject"]}' + (f": {consts}" if consts else ""))
    lines += ["", f'Tests: {md(t["test_dir_url"], "EELS tests at " + release_short(t["newest_release"]))}']
    if t["state"] == "no-run":
        lines.append(f"- no {config.SIMULATOR} run for this client")
    else:
        lines.append(f'- {t["passed"]}/{t["total"]} pass on `{t["release"]}`, {md(t["run_url"], "hive run")}')
        lines += [f"- fails: `{f}`" for f in t["failed"][:20]]
        if len(t["failed"]) > 20:
            lines.append(f'- and {len(t["failed"]) - 20} more failing case(s)')
    lines += ["", f'{doc["client_label"]} PRs mentioning EIP-{doc["eip"]} ({c["repo"]}):']
    if c["state"] == "unreachable":
        lines.append("- lookup failed in this snapshot; check the repo by hand")
    elif c["state"] == "not-collected":
        lines.append("- not collected in this snapshot")
    elif not c["prs"]:
        lines.append("- none found by title")
    else:
        lines += [pr_line(p) for p in c["prs"]]
    if doc["pending_spec"]:
        lines += ["", "Open spec PRs (not merged, not counted):"]
        lines += [f'- {md(p["url"], p["repo"].split("/")[1] + "#" + str(p["number"]))} {p["title"]}' for p in doc["pending_spec"]]
    if doc["hints"]["state"] == "ok":
        lines += ["", "Where the constants live in this client:"]
        lines += [f'- `{h["name"]}` {h["state"]}: {md(h["url"], h["url"].rsplit("/", 1)[-1])}' for h in doc["hints"]["rows"]]
    lines += ["", f'Source: {md(doc["page"], config.NAME)}']
    return "\n".join(lines) + "\n"
