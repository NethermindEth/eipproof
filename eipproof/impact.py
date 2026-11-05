import argparse
import json
import os
import re
import sys

from . import config, handoff, sources

CLIENT = "nethermind"
LIMIT = 150
FILE_PAGES = 30
COLLECT_FILE_PAGES = 3
COMMIT_PAGES = 3
PER_KIND = 5
MAX_FAILED = 3
CHECKED = {}
KINDS = ["title", "body", "commit", "path", "code", "constant"]
MENTION = re.compile(r"(?:(?<![A-Za-z0-9])[Ee][Ii][Pp]|(?<=[a-z0-9])Eip)[-_ ]?(\d{3,5})(?!\d)")
ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`\s*\|(.*)$")
OTHER_EIP = re.compile(r"eip-(\d+)", re.I)
WORD = re.compile(r"[A-Za-z0-9_]")


def mentions(text, tracked):
    return {m.group(1) for m in MENTION.finditer(text or "") if m.group(1) in tracked}


def mention_tokens(text, tracked):
    out = []
    for m in MENTION.finditer(text or ""):
        if m.group(1) not in tracked:
            continue
        start, end = m.start(), m.end()
        while start > 0 and WORD.match(text[start - 1]):
            start -= 1
        while end < len(text) and WORD.match(text[end]):
            end += 1
        out.append((m.group(1), text[start:end]))
    return out


def spec_constants(text, eip):
    names = set()
    for line in (text or "").splitlines():
        m = ROW.match(line.strip())
        if m and not set(OTHER_EIP.findall(m.group(2))) - {eip}:
            names.add(m.group(1))
    return sorted(names)


def forms(name):
    parts = name.split("_")
    return [name] + (["".join(p.capitalize() for p in parts)] if len(parts) >= 3 else [])


def changed_lines(patch):
    return [line[1:] for line in (patch or "").splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def add(found, eip, item):
    rows = found.setdefault(eip, [])
    if item not in rows and sum(r["kind"] == item["kind"] for r in rows) < PER_KIND:
        rows.append(item)


def evidence(pull, files, commits, consts):
    tracked = set(consts)
    found = {}
    for eip in sorted(mentions(pull.get("title"), tracked)):
        add(found, eip, {"kind": "title"})
    for eip in sorted(mentions(pull.get("body"), tracked)):
        add(found, eip, {"kind": "body"})
    for c in commits:
        head = c["commit"]["message"].split("\n", 1)[0]
        for eip in sorted(mentions(head, tracked)):
            add(found, eip, {"kind": "commit", "sha": c["sha"], "text": head})
    patterns = [(eip, name, f, re.compile(rf"(?<![A-Za-z0-9_]){f}(?![A-Za-z0-9_])")) for eip, names in sorted(consts.items()) for name in names for f in forms(name)]
    for fl in files:
        path = fl["filename"]
        for p in (path, fl.get("previous_filename")):
            for eip in sorted(mentions(p, tracked)):
                add(found, eip, {"kind": "path", "file": path})
        lines = changed_lines(fl.get("patch"))
        for line in lines:
            for eip, token in mention_tokens(line, tracked):
                add(found, eip, {"kind": "code", "token": token, "file": path})
        text = "\n".join(lines)
        for eip, name, f, pat in patterns:
            if pat.search(text):
                add(found, eip, {"kind": "constant", "name": name, "as": f, "file": path})
    for rows in found.values():
        rows.sort(key=lambda r: KINDS.index(r["kind"]))
    return found


def pages(path, max_pages):
    out = []
    for page in range(1, max_pages + 1):
        rows = handoff.fetch(f"{path}?per_page=100&page={page}")
        out += rows
        if len(rows) < 100:
            return out, False
    return out, True


def fetch_pr(repo, number, max_file_pages=FILE_PAGES):
    pull = handoff.fetch(f"repos/{repo}/pulls/{number}")
    files, truncated = pages(f"repos/{repo}/pulls/{number}/files", max_file_pages)
    commits, _ = pages(f"repos/{repo}/pulls/{number}/commits", COMMIT_PAGES)
    return {"pull": pull, "files": files, "commits": commits, "files_truncated": truncated}


def spec_text(eip, head):
    return sources.gh_raw(f"repos/{config.EIPS_REPO}/contents/EIPS/eip-{eip}.md?ref={head}")


def client_of(repo):
    return next((c for c, r in config.CLIENT_REPO.items() if r.lower() == repo.lower()), None)


def fork_prefix(fork):
    sub = config.FORKS[fork]["SUBDIR"]
    return f"{sub}/" if sub else ""


def fork_url(fork):
    return "/".join(p for p in (config.SITE_ROOT, config.FORKS[fork]["SUBDIR"]) if p)


def local_site(root):
    def get(path):
        with open(os.path.join(root, path)) as f:
            return f.read()
    return get


def url_site(base):
    return lambda path: sources.http_get(f"{base.rstrip('/')}/{path}").decode()


def read_forks(get):
    out, missing = {}, []
    for fork in config.FORKS:
        try:
            out[fork] = json.loads(get(fork_prefix(fork) + "api/eips.json"))
        except Exception:
            if fork == config.DEFAULT_FORK:
                raise
            missing.append(fork)
    return out, missing


def cell_of(get, fork, eip, client):
    doc = json.loads(get(fork_prefix(fork) + f"api/eip/{eip}.json"))
    c = next((c for c in doc["cells"] if c["client"] == client), None)
    return c and {"client": client, "headline": c["headline"], "text": c["text"], "why": c["why"]}


def report(repo, number, get):
    got = fetch_pr(repo, number)
    pull = got["pull"]
    client = client_of(repo)
    doc = {"repo": repo, "number": pull["number"], "title": pull["title"], "url": pull["html_url"], "draft": bool(pull.get("draft")),
           "head": pull["head"]["sha"], "client": client, "files": len(got["files"]), "files_truncated": got["files_truncated"],
           "state": "ok", "snapshot": None, "forks_missing": [], "eips": []}
    try:
        forks, doc["forks_missing"] = read_forks(get)
    except Exception as e:
        doc.update(state="site-unreachable", reason=f"{type(e).__name__}: {e}")
        return doc
    doc["snapshot"] = forks[config.DEFAULT_FORK]["snapshot"]
    rows = {(fork, r["eip"]): r for fork, d in forks.items() for r in d["eips"]}
    texts, spec_errors = {}, []
    for fork, eip in sorted(rows):
        if eip in texts:
            continue
        try:
            texts[eip] = spec_text(eip, rows[(fork, eip)].get("head") or config.EIPS_BRANCH)
        except Exception:
            texts[eip] = ""
            spec_errors.append(eip)
    doc["spec_unread"] = sorted(spec_errors)
    consts = {eip: spec_constants(t, eip) for eip, t in texts.items()}
    found = evidence(pull, got["files"], got["commits"], consts)
    for fork, eip in sorted(rows, key=lambda k: (list(config.FORKS).index(k[0]), k[1])):
        if eip not in found:
            continue
        r = rows[(fork, eip)]
        cell = None
        if client and r.get("test_dir"):
            try:
                cell = cell_of(get, fork, eip, client)
            except Exception:
                cell = None
        head = r.get("head")
        doc["eips"].append({
            "eip": eip, "fork": fork, "title": r.get("title"), "status": r.get("status"), "evidence": found[eip],
            "spec": {"head": head, "url": f"{config.GITHUB}/{config.EIPS_REPO}/blob/{head or config.EIPS_BRANCH}/EIPS/eip-{eip}.md",
                     "behind": r.get("behind"), "constants": len(consts.get(eip, []))},
            "tests": {"test_dir": r.get("test_dir"), "eels_todo": r.get("eels_todo")},
            "cell": cell,
            "page": f"{fork_url(fork)}/index.html#{eip}-{client}" if cell else f"{fork_url(fork)}/eip-{eip}.html",
        })
    return doc


def md_text(s):
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
    return re.sub(r"\s*[\r\n]+\s*", " ", s)


def code(s):
    return f"`{md_text(s).replace('`', '')}`"


def evidence_words(ev):
    base = lambda p: p.rsplit("/", 1)[-1]
    k = ev["kind"]
    if k == "commit":
        return f'commit {ev["sha"][:8]}'
    if k == "path":
        return f'path {base(ev["file"])}'
    if k == "code":
        return f'code {ev["token"]} in {base(ev["file"])}'
    if k == "constant":
        return f'constant {ev["name"]}' + (f' as {ev["as"]}' if ev["as"] != ev["name"] else "") + f' in {base(ev["file"])}'
    return k


def evidence_md(rows, limit=6):
    def one(ev):
        base = lambda p: md_text(p.rsplit("/", 1)[-1])
        k = ev["kind"]
        if k == "commit":
            return f'commit {code(ev["sha"][:8])}'
        if k == "path":
            return f'path {base(ev["file"])}'
        if k == "code":
            return f'code {code(ev["token"])} in {base(ev["file"])}'
        if k == "constant":
            return f'constant {code(ev["name"])}' + (f' as {code(ev["as"])}' if ev["as"] != ev["name"] else "") + f' in {base(ev["file"])}'
        return k
    out = "; ".join(one(e) for e in rows[:limit])
    return out + (f"; and {len(rows) - limit} more" if len(rows) > limit else "")


def tests_md(r):
    if not r["tests"]["test_dir"]:
        return "no EELS tests yet"
    b = r["spec"]["behind"]
    if b is None:
        return "EELS tests, version unknown"
    return "EELS tests match the spec text" if b == 0 else f"EELS tests are {b} spec change(s) behind"


def markdown(doc):
    label = config.CLIENT_LABEL.get(doc["client"], "Client") if doc["client"] else None
    lines = ["<!-- eipproof pr-impact -->",
             f'### {config.NAME}: tracked EIPs in [{md_text(doc["repo"])}#{doc["number"]}]({doc["url"]}) {md_text(doc["title"])}', ""]
    if doc["state"] == "site-unreachable":
        lines.append(f'{config.NAME} could not read the site ({md_text(doc.get("reason", ""))}), so no status is shown. The PR itself was read.')
        return "\n".join(lines) + "\n"
    if not doc["eips"]:
        lines.append("No tracked EIP is named in the title, body, commit headlines, file paths or changed lines of this PR, "
                     "and no changed line uses a spec constant name.")
    else:
        lines += [f'| EIP | Fork | Found in | Spec | Tests | {label or "Matrix"} |', "|---|---|---|---|---|---|"]
        for r in doc["eips"]:
            spec = f'[text at {r["spec"]["head"][:8]}]({r["spec"]["url"]})' if r["spec"]["head"] else f'[text]({r["spec"]["url"]})'
            if r["cell"]:
                cell = f'[{md_text(r["cell"]["text"])}]({r["page"]})'
            elif not doc["client"]:
                cell = f"not a tracked client repo, [EIP page]({r['page']})"
            else:
                cell = f"no matrix cell, [EIP page]({r['page']})"
            lines.append(f'| [EIP-{r["eip"]}]({r["page"]}) {md_text(r["title"] or "")} | {r["fork"]} | {evidence_md(r["evidence"])} | {spec} | {tests_md(r)} | {cell} |')
    notes = []
    if doc["files_truncated"]:
        notes.append(f'GitHub lists only the first {doc["files"]} changed files; the rest were not read.')
    if doc.get("spec_unread"):
        notes.append("Spec text not read for EIP " + ", ".join(doc["spec_unread"]) + ", so constants were not matched there.")
    if doc.get("forks_missing"):
        notes.append("Fork(s) not read: " + ", ".join(doc["forks_missing"]) + ".")
    lines += [""] + notes + ([""] if notes else [])
    lines.append(f'A match means an EIP number or a spec constant name appears in this PR; it says nothing about correctness. '
                 f'Snapshot {md_text(doc["snapshot"])}, [{config.NAME}]({config.SITE_ROOT}/index.html).')
    return "\n".join(lines) + "\n"


def collect(repo, texts, log=print, limit=LIMIT):
    client = client_of(repo)
    try:
        pulls, truncated = handoff.list_prs(repo, "open")
    except Exception as e:
        log(f"::warning title=pr impact::{repo}: {type(e).__name__}")
        return {"repo": repo, "client": client, "state": "unreachable", "reason": type(e).__name__, "prs": []}
    consts = {eip: spec_constants(t, eip) for eip, t in texts.items()}
    prs, checked, failed = [], 0, 0
    for p in pulls[:limit]:
        key = (repo, p["number"], p["head"]["sha"])
        if key not in CHECKED:
            if failed >= MAX_FAILED:
                break
            try:
                CHECKED[key] = pages(f"repos/{repo}/pulls/{p['number']}/files", COLLECT_FILE_PAGES)
            except Exception as e:
                failed += 1
                log(f"::warning title=pr impact::{repo}#{p['number']}: {type(e).__name__}")
                continue
        checked += 1
        files, cut = CHECKED[key]
        found = evidence(p, files, [], consts)
        if found:
            prs.append({"number": p["number"], "title": p["title"], "url": p["html_url"], "draft": bool(p.get("draft")),
                        "updated": p["updated_at"][:10], "head": p["head"]["sha"], "files_truncated": cut, "evidence": found})
    log(f"impact {repo}: {checked} open PR(s) checked, {len(prs)} touch a tracked EIP, {len(pulls) - checked} unchecked")
    return {"repo": repo, "client": client, "state": "ok", "checked": checked, "unchecked": len(pulls) - checked,
            "truncated": truncated, "prs": prs}


def main(argv=None):
    p = argparse.ArgumentParser(prog=f"{config.NAME} pr-impact", description="which tracked EIPs a pull request touches, with their current status")
    p.add_argument("repo", help="owner/repo")
    p.add_argument("number", type=int)
    p.add_argument("--site", default=config.SITE_ROOT, help="site URL or a local site directory")
    p.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    args = p.parse_args(argv)
    get = url_site(args.site) if re.match(r"https?://", args.site) else local_site(args.site)
    doc = report(args.repo, args.number, get)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=True)
    sys.stdout.write(markdown(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
