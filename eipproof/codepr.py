import os
import re
import subprocess
from datetime import datetime, timezone

from . import config, handoff, sources

MIN_CODE_FILES = 2
SHOWN_FILES = 5
NOT_STARTED, IN_PROGRESS, IMPLEMENTED, STALE = "not-started", "in-progress", "implemented", "stale"
WORD = {IMPLEMENTED: "code merged", STALE: "spec changed since", IN_PROGRESS: "PR open", NOT_STARTED: "no named code or PR"}
PILL = {IMPLEMENTED: "ok", STALE: "stale", IN_PROGRESS: "warn", NOT_STARTED: "none"}


def names_eip(text, eip):
    return re.search(rf"(?:(?<![A-Za-z0-9])[Ee][Ii][Pp]|(?<=[a-z0-9])Eip)[-_ ]?{eip}(?!\d)", text or "") is not None


def names(text, eip):
    return names_eip(text, eip) or any(
        re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", text or "", re.I) for alias in config.EIP_ALIASES.get(eip, ()))


def utc(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def eip_layer(eip, info):
    return config.EIP_LAYERS.get(eip) or ("el" if info.get("test_dir") else "both")


def clients_for(layer):
    return [c for c, meta in config.CODE_CLIENTS.items() if layer in ("both", meta["layer"])]


def normative_dates(info, attestations):
    out = []
    changes = {d["commit"]: d for d in info.get("revisions", []) + info.get("deltas", [])}
    for d in changes.values():
        attested = [a for a in attestations if a["eip"] == info["eip"] and d["commit"].startswith(str(a["commit"]))]
        if not attested or attested[-1].get("kind") != "editorial":
            out.append(d["date"])
    return out


def effective(pr, branch):
    if pr["state"] != "merged" or pr.get("base") in (None, branch):
        return pr
    if pr.get("landed"):
        return {**pr, "base": branch}
    return {**pr, "state": "merged-elsewhere"}


def status(prs, files, spec_dates, branch):
    prs = [effective(p, branch) for p in prs]
    merged = [utc(p["merged"]) for p in prs if p["state"] == "merged" and p.get("merged")]
    if merged or files >= MIN_CODE_FILES:
        if merged and any(utc(d) > max(merged) for d in spec_dates):
            return STALE
        return IMPLEMENTED
    return IN_PROGRESS if any(p["state"] in ("open", "merged-elsewhere") for p in prs) else NOT_STARTED


def tree_paths(client):
    meta = config.CODE_CLIENTS[client]
    path = os.path.join(sources.CACHE, "trees", f"{client}.git")
    if not os.path.isdir(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["git", "init", "--quiet", "--bare", path], check=True)
    url = f"{config.GITHUB}/{meta['repo']}.git"
    ref = f"refs/heads/{meta['branch']}"
    sources.git(path, "fetch", "--quiet", "--force", "--depth=1", "--filter=blob:none", url, f"+{ref}:{ref}")
    commit = sources.git(path, "rev-parse", ref).strip()
    return commit, sources.git(path, "ls-tree", "-r", "--name-only", commit).splitlines()


def pr_row(pull):
    return {**handoff.pr_row(pull), "base": (pull.get("base") or {}).get("ref"), "merge_sha": pull.get("merge_commit_sha")}


def landed(repo, branch, pr):
    if not pr.get("merge_sha"):
        return False
    try:
        cmp = handoff.fetch(f"repos/{repo}/compare/{branch}...{pr['merge_sha']}?per_page=1")
    except Exception:
        return False
    return cmp.get("status") in ("behind", "identical")


def client_prs(repo, eips, since):
    pulls, truncated = handoff.list_prs(repo, "open")
    closed, cut = handoff.list_prs(repo, "closed", since)
    found = {}
    for pull in pulls + [p for p in closed if p.get("merged_at")]:
        for eip in eips:
            if names(pull["title"], eip) and all(p["number"] != pull["number"] for p in found.get(eip, [])):
                found.setdefault(eip, []).append(pr_row(pull))
    return found, truncated or cut


def collect_client(client, eips, since):
    meta = config.CODE_CLIENTS[client]
    commit, paths = tree_paths(client)
    found, truncated = client_prs(meta["repo"], eips, since)
    out = {}
    for eip in eips:
        files = [p for p in paths if names(p, eip)]
        prs = []
        for p in found.get(eip, []):
            if p["state"] == "merged" and p.get("base") not in (None, meta["branch"]):
                p = {**p, "landed": landed(meta["repo"], meta["branch"], p)}
            prs.append(p)
        prs.sort(key=lambda p: (p["state"] != "open", -p["number"]))
        out[eip] = {"files": len(files), "paths": files[:SHOWN_FILES], "prs": prs}
    return {"state": "ok", "repo": meta["repo"], "branch": meta["branch"], "commit": commit, "truncated": truncated,
            "merged_since": since[:10], "eips": out}


def collect(snap_eips, log=print, now=None):
    since = handoff.since_date(now)
    wanted = {}
    for eip, info in snap_eips.items():
        for client in clients_for(eip_layer(eip, info)):
            wanted.setdefault(client, []).append(eip)
    out = {}
    for client, eips in wanted.items():
        repo = config.CODE_CLIENTS[client]["repo"]
        try:
            out[client] = collect_client(client, sorted(eips), since)
            hits = sum(1 for e in out[client]["eips"].values() if e["files"] or e["prs"])
            log(f"code  {repo}@{out[client]['commit'][:8]}: {hits}/{len(eips)} EIP(s) with code or PRs")
        except Exception as e:
            out[client] = {"state": "unreachable", "repo": repo, "reason": type(e).__name__, "eips": {}}
            log(f"::warning title=code status::{repo}: {type(e).__name__}")
    return out


def cell(snap, client, eip, attestations=()):
    meta = config.CODE_CLIENTS[client]
    block = (snap.get("code_status") or {}).get(client)
    base = {"client": client, "label": meta["label"], "repo": meta["repo"]}
    if block is None or (block["state"] == "ok" and eip not in block["eips"]):
        return {**base, "state": "not-collected"}
    if block["state"] != "ok":
        return {**base, "state": "unreachable", "reason": block.get("reason")}
    ev = block["eips"][eip]
    st = status(ev["prs"], ev["files"], normative_dates(snap["eips"][eip], list(attestations)), block["branch"])
    return {**base, "state": "ok", "branch": block["branch"], "commit": block["commit"], "truncated": block.get("truncated", False),
            "status": st, "files": ev["files"], "paths": ev["paths"], "prs": [effective(p, block["branch"]) for p in ev["prs"]]}


def cells(snap, eip, attestations=()):
    return [cell(snap, c, eip, attestations) for c in clients_for(eip_layer(eip, snap["eips"][eip]))]


def plural(n, word):
    return f"{n} {word}{'s' if n != 1 else ''}"


def evidence_text(c):
    if c["state"] == "not-collected":
        return "not collected in this snapshot"
    if c["state"] == "unreachable":
        return "lookup failed in this snapshot"
    parts = []
    if c["files"]:
        parts.append(f"{plural(c['files'], 'file')} named for the EIP on {c['branch']}")
    merged = [p for p in c["prs"] if p["state"] == "merged"]
    pending = [p for p in c["prs"] if p["state"] in ("open", "merged-elsewhere")]
    if merged:
        parts.append(f"{plural(len(merged), 'merged PR')}")
    if pending:
        parts.append(f"{plural(len(pending), 'open or unlanded PR')}")
    return ", ".join(parts) or f"no file or PR title names the EIP on {c['branch']}"
