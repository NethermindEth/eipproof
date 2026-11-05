import os
import re
import subprocess
from urllib.parse import quote

import yaml

from . import config, index, sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC_ROW = re.compile(r"^\s*\|\s*`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`\s*\|\s*`?([^|`\s]+)")
STATES = ("match", "differs", "not-located", "unparsed", "spec-tbd", "unreachable")
STATUSES = ("suspect", "confirmed")
ROW_KEYS = {"eip", "name", "client", "ref", "sha", "spec", "value", "path", "line", "url", "status", "predates_spec"}


def load_targets(fork=None):
    path = os.path.join(ROOT, "targets", f"{fork or config.FORK}.yaml")
    if not os.path.exists(path):
        return []
    return yaml.safe_load(open(path)) or []


def spec_table(text):
    out = {}
    for line in text.splitlines():
        m = _SPEC_ROW.match(line)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2)
    return out


def number(raw):
    try:
        return int(raw.replace("_", ""), 0)
    except (AttributeError, ValueError):
        return None


def locate(text, ident):
    pat = re.compile(r"(?<![\w.:])" + re.escape(ident) + r"\s*(?::[^=\n]*)?=(?![=>])\s*([^;,\n{}]+)")
    return [(text.count("\n", 0, m.start()) + 1, m.group(1).strip()) for m in pat.finditer(text)]


def observe(text, ident, path):
    if text is None:
        return {"state": "not-located", "path": path, "reason": "file not in this commit"}
    hits = locate(text, ident)
    if not hits:
        return {"state": "not-located", "path": path, "reason": f"no definition of {ident}"}
    values = {number(raw) for _, raw in hits}
    line, raw = hits[0]
    if len(values) > 1 or None in values:
        return {"state": "unparsed", "path": path, "line": line, "raw": raw, "ident": ident}
    return {"state": "found", "path": path, "line": line, "raw": raw, "value": values.pop(), "ident": ident}


def judge(spec, ob):
    if ob.get("state") in ("not-located", "unparsed", "unreachable"):
        return ob["state"]
    if spec is None:
        return "spec-tbd"
    return "match" if ob["value"] == spec else "differs"


def spec_history(eips_repo, eip):
    path = f"EIPS/eip-{eip}.md"
    tables = []
    for line in sources.git(eips_repo, "log", config.EIPS_BRANCH, "--format=%H%x09%cI", "--", path).splitlines():
        commit, date = line.split("\t")
        try:
            tables.append((commit, date, spec_table(sources.git(eips_repo, "show", f"{commit}:{path}"))))
        except subprocess.CalledProcessError:
            break
    return path, tables


def since(tables, name):
    head = tables[0][2].get(name)
    first = None
    for commit, date, table in tables:
        if table.get(name) != head:
            break
        first = {"commit": commit, "date": date}
    return first


def fetch_ref(repo, ref):
    c = sources.gh_api(f"repos/{repo}/commits/{quote(ref, safe='')}")
    return c["sha"], c["commit"]["committer"]["date"]


def fetch_file(repo, sha, path):
    try:
        return sources.gh_raw(f"repos/{repo}/contents/{quote(path)}?ref={sha}")
    except subprocess.CalledProcessError:
        return None


def collect(eips_repo, log=print, fetch_ref=fetch_ref, fetch_file=fetch_file):
    eips = []
    for t in load_targets():
        eip = str(t["eip"])
        path, tables = spec_history(eips_repo, eip)
        if not tables:
            log(f"diverge EIP-{eip}: no EIP text on {config.EIPS_BRANCH}")
            continue
        head_commit, head_date, table = tables[0]
        names = sorted({n for c in t["clients"].values() for f in c["files"].values() for n in f})
        consts = [{"name": n, "raw": table.get(n), "value": number(table.get(n)), "since": since(tables, n)} for n in names]
        refs = []
        for client, spec in t["clients"].items():
            repo = config.CLIENT_REPO[client]
            for r in spec["refs"]:
                row = {"client": client, "repo": repo, "ref": r["ref"], "pr": r.get("pr")}
                try:
                    row["sha"], row["date"] = fetch_ref(repo, r["ref"])
                except Exception as e:
                    refs.append({**row, "state": "unreachable", "error": f"{type(e).__name__}"})
                    continue
                obs = {}
                for fpath, idents in spec["files"].items():
                    text = fetch_file(repo, row["sha"], fpath)
                    for name, ident in idents.items():
                        obs[name] = observe(text, ident, fpath)
                refs.append({**row, "state": "ok", "obs": obs})
                log(f"diverge EIP-{eip} {client} {r['ref']} {row['sha'][:8]}: {len(obs)} constant(s)")
        eips.append({"eip": eip, "spec": {"commit": head_commit, "date": head_date, "path": path}, "constants": consts, "refs": refs})
    return {"eips": eips}


def blob_url(ref, ob):
    return f'{config.GITHUB}/{ref["repo"]}/blob/{ref["sha"]}/{ob["path"]}' + (f'#L{ob["line"]}' if ob.get("line") else "")


def failing(snap, eip, client):
    run = (snap.get("runs") or {}).get(client) or {}
    return bool(((run.get("eips") or {}).get(eip) or {}).get("failed"))


def doc(snap):
    block = snap.get("divergence") or {"eips": []}
    eips, rows = [], []
    for e in block["eips"]:
        refs = []
        for ref in e["refs"]:
            cells, counts = {}, {s: 0 for s in STATES}
            for c in e["constants"]:
                ob = ref.get("obs", {}).get(c["name"], {"state": "unreachable"}) if ref["state"] == "ok" else {"state": "unreachable"}
                state = judge(c["value"], ob)
                counts[state] += 1
                cells[c["name"]] = {"state": state, "value": ob.get("value"), "raw": ob.get("raw"), "reason": ob.get("reason"),
                                    "url": blob_url(ref, ob) if ref["state"] == "ok" and ob.get("path") else None}
                if state == "differs":
                    predates = bool(c["since"]) and index.iso(ref["date"]) < index.iso(c["since"]["date"])
                    rows.append({"eip": e["eip"], "name": c["name"], "client": ref["client"], "ref": ref["ref"], "sha": ref["sha"],
                                 "spec": c["value"], "value": ob["value"], "path": ob["path"], "line": ob["line"], "url": blob_url(ref, ob),
                                 "status": "confirmed" if failing(snap, e["eip"], ref["client"]) else "suspect",
                                 "predates_spec": predates, "spec_since": c["since"], "ref_date": ref["date"]})
            refs.append({k: ref.get(k) for k in ("client", "repo", "ref", "pr", "sha", "date", "state")} | {"counts": counts, "cells": cells})
        eips.append({"eip": e["eip"], "spec": {**e["spec"], "url": f'{config.GITHUB}/{config.EIPS_REPO}/blob/{e["spec"]["commit"]}/{e["spec"]["path"]}'},
                     "constants": e["constants"], "refs": refs})
    return {"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"),
            "eips": eips, "divergences": rows}


def check_doc(d):
    errs = []
    for k in ("fork", "snapshot", "source", "eips", "divergences"):
        if k not in d:
            errs.append(f"divergences.json: missing {k}")
    for i, r in enumerate(d.get("divergences") or []):
        missing = ROW_KEYS - r.keys()
        if missing:
            errs.append(f"divergences.json: row {i} missing {sorted(missing)}")
        if r.get("status") not in STATUSES:
            errs.append(f"divergences.json: row {i} status {r.get('status')!r}")
        if "url" in r and not str(r["url"]).startswith(config.GITHUB + "/"):
            errs.append(f"divergences.json: row {i} url {r['url']!r}")
    for e in d.get("eips") or []:
        for ref in e.get("refs") or []:
            for name, c in (ref.get("cells") or {}).items():
                if c.get("state") not in STATES:
                    errs.append(f"divergences.json: EIP-{e.get('eip')} {ref.get('ref')} {name} state {c.get('state')!r}")
    return errs
