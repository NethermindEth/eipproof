import base64
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from . import config, index, sources


def spec_revisions(eips_repo, eip):
    path = f"EIPS/eip-{eip}.md"
    raw = sources.git(eips_repo, "log", config.EIPS_BRANCH, "--no-abbrev", "--raw", "--format=%x00%H%x09%cI%x09%s", "--", path)
    revs = []
    for chunk in raw.split("\x00")[1:]:
        lines = chunk.strip().splitlines()
        commit, date, subject = lines[0].split("\t", 2)
        blob = next((l.split()[3] for l in lines[1:] if l.startswith(":") and l.endswith(path)), None)
        if blob and set(blob) != {"0"}:
            revs.append({"commit": commit, "date": date, "subject": subject, "blob": blob})
    for i, r in enumerate(reversed(revs)):
        r["order"] = i
    return path, sorted(revs, key=lambda r: r["order"])


def eels_test_dirs(eels_repo, tag):
    names = sources.git(eels_repo, "ls-tree", "--name-only", f"{tag}:{config.TEST_ROOT}").split()
    return {n[3:].split("_", 1)[0]: f"{config.TEST_ROOT}/{n}" for n in names if n.startswith("eip")}


def candidate_search(eels_repo, tag, test_dir, delta):
    log = sources.git(eels_repo, "log", "--first-parent", "--name-only", "--format=%x00%H%x09%aI%x09%s", tag, "--", test_dir)
    window, files = [], set()
    for chunk in log.split("\x00")[1:]:
        lines = [l for l in chunk.strip().splitlines() if l]
        commit, adate, subject = lines[0].split("\t", 2)
        if index.in_window(delta["date"], adate):
            window.append({"commit": commit, "author_date": adate, "subject": subject})
            files.update(f for f in lines[1:] if f.rsplit("/", 1)[-1].startswith("test_") and f.endswith(".py"))
    sources_at_tag = {}
    for f in sorted(files):
        try:
            sources_at_tag[f] = sources.git(eels_repo, "show", f"{tag}:{f}")
        except Exception:
            continue
    return window, index.score_candidates(delta["tokens"], sources_at_tag)


def shipped_pin(eels_repo, tag, spec, eip):
    try:
        return (index.parse_pins(sources.git(eels_repo, "show", f"{tag}:{spec}")).get(eip) or {}).get("blob")
    except Exception:
        return None


def pin_history(eels_repo, tag, test_dir, eip):
    spec = f"{test_dir}/spec.py"
    log = sources.git(eels_repo, "log", "--format=%x00%H%x09%cI%x09%s", tag, "--", spec)
    out = []
    for chunk in log.split("\x00")[1:]:
        commit, date, subject = chunk.strip().split("\t", 2)
        pin = index.parse_pins(sources.git(eels_repo, "show", f"{commit}:{spec}")).get(eip)
        if not pin:
            continue
        files = [f.rsplit("/", 1)[-1] for f in sources.git(eels_repo, "show", "--name-only", "--format=", commit, "--", test_dir).split() if f != spec]
        released = sorted(sources.git(eels_repo, "tag", "--contains", commit, "--list", f"{config.RELEASE_PREFIX}*").split(), key=index.release_key)
        shipped = next((t for t in released if shipped_pin(eels_repo, t, spec, eip) == pin["blob"]), None)
        out.append({"commit": commit, "date": date, "subject": subject, "pr": index.pr_number(subject), "blob": pin["blob"], "files": files,
                    "release": shipped, "superseded": bool(released) and not shipped})
    return list(reversed(out))


def pending_prs(eip):
    hits = sources.gh_api(f"search/issues?q=repo:{config.EIPS_REPO}+is:pr+is:open+in:title+EIP-{eip}&per_page=20")
    out = []
    for item in hits.get("items", []):
        files = sources.gh_api(f"repos/{config.EIPS_REPO}/pulls/{item['number']}/files?per_page=100")
        if any(f["filename"] == f"EIPS/eip-{eip}.md" for f in files):
            pr = sources.gh_api(f"repos/{config.EIPS_REPO}/pulls/{item['number']}")
            out.append({"number": pr["number"], "title": pr["title"], "url": pr["html_url"], "state": pr["state"],
                        "merged": pr["merged"], "head": pr["head"]["sha"], "api": f"https://api.github.com/repos/{config.EIPS_REPO}/pulls/{pr['number']}"})
    return out


def collect_specs(eips_repo, eels_repo, tag, log):
    tag_commit = sources.git(eels_repo, "rev-list", "-n1", tag).strip()
    tag_date = sources.git(eels_repo, "show", "-s", "--format=%cI", tag_commit).strip()
    dirs = eels_test_dirs(eels_repo, tag)
    stages = index.meta_stages(sources.git(eips_repo, "show", f"{config.EIPS_BRANCH}:EIPS/eip-{config.META_EIP}.md"))
    eips = {}
    wanted = sorted(set(index.listed_eips(stages)) | set(dirs), key=int)
    for eip in wanted:
        test_dir = dirs.get(eip)
        path, revs = spec_revisions(eips_repo, eip)
        if not revs:
            log(f"spec  EIP-{eip}: not in {config.EIPS_REPO}, skipped")
            continue
        if not test_dir:
            head = revs[-1]
            front = index.frontmatter(sources.git(eips_repo, "show", f"{head['commit']}:{path}"))
            eips[eip] = {
                "eip": eip, "path": path, "test_dir": None, "checked": f"{config.TEST_ROOT}/eip{eip}_*",
                "head": head["commit"], "head_blob": head["blob"], "head_date": head["date"],
                "revisions": [{k: r[k] for k in ("commit", "date", "subject", "blob")} for r in revs[-12:]],
                "pin": None, "deltas": [], "pending": pending_prs(eip),
                "title": front.get("title"), "status": front.get("status"), "category": front.get("category"), "stage": stages.get(eip, []),
            }
            log(f"spec  EIP-{eip}: no tests under {config.TEST_ROOT} at {tag}")
            continue
        pins = index.parse_pins(sources.git(eels_repo, "show", f"{tag}:{test_dir}/spec.py"))
        pin = index.resolve_pin(revs, pins[eip]["blob"], tag_date)
        deltas = []
        for r in index.deltas_after(revs, pin["commit"]):
            diff = sources.git(eips_repo, "show", "--format=", r["commit"], "--", path)
            d = {**r, "diff": diff, "tokens": index.delta_tokens(diff), "constants": index.constant_changes(diff)}
            window, cands = candidate_search(eels_repo, tag, test_dir, d)
            d["window"], d["candidates"] = window, cands
            deltas.append(d)
        head = revs[-1]
        front = index.frontmatter(sources.git(eips_repo, "show", f"{head['commit']}:{path}"))
        eips[eip] = {
            "eip": eip, "path": path, "test_dir": test_dir,
            "head": head["commit"], "head_blob": head["blob"], "head_date": head["date"],
            "revisions": [{k: r[k] for k in ("commit", "date", "subject", "blob")} for r in revs[-12:]],
            "pin": {**pin, "release": tag, "spec_py": f"{config.GITHUB}/{config.EELS_REPO}/blob/{tag.replace('@', '%40')}/{test_dir}/spec.py"},
            "deltas": deltas,
            "pin_history": pin_history(eels_repo, tag, test_dir, eip),
            "pending": pending_prs(eip),
            "title": front.get("title"), "status": front.get("status"), "category": front.get("category"), "stage": stages.get(eip, []),
        }
        log(f"spec  EIP-{eip}: pin {pin['blob'][:8]} -> {pin['commit'][:8] if pin['commit'] else '?'}  head {head['commit'][:8]}  deltas {len(deltas)}  pending {len(eips[eip]['pending'])}")
    return {"tag": tag, "tag_commit": tag_commit, "tag_date": tag_date, "eips": eips}


def collect_runs(listing, out_dir, log):
    runs, cases_dir = {}, os.path.join(out_dir, "cases")
    os.makedirs(cases_dir, exist_ok=True)
    picked = index.pick_runs(listing)
    for client in config.CLIENTS:
        row = picked.get(client)
        if row is None:
            log(f"run   {client}: no {config.SIMULATOR} run")
            continue
        release = index.release_from_simlog(sources.hive_simlog_head(row["simLog"]))
        path = sources.hive_result_path(row["fileName"])
        with open(path, "rb") as f:
            raw = f.read()
        doc = json.loads(raw)
        del raw
        results, per_eip, client_wide = index.summarize_cases(doc["testCases"])
        version = next(iter(doc["clientVersions"].values()))
        ids_hash, ids_blob, bits = index.bitmap(results)
        case_file = os.path.join(cases_dir, f"{ids_hash}.txt.gz")
        if not os.path.exists(case_file):
            with gzip.open(case_file, "wb") as g:
                g.write(ids_blob)
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        runs[client] = {
            "client": client, "version": version, "commit": index.commit_of(version),
            "image": index.image_of(doc["runMetadata"]), "release": release, "simulator": row["name"],
            "start": row["start"], "end": row["end"], "ntests": row["ntests"], "fails": row["fails"],
            "file": row["fileName"], "file_sha256": sha, "sim_log": f"{config.HIVE}/results/{row['simLog']}",
            "url": f"{config.HIVE}/suite.html?" + urlencode({"suiteid": row["fileName"], "suitename": row["name"]}),
            "raw_url": f"{config.HIVE}/results/{row['fileName']}",
            "cases_hash": ids_hash, "bitmap": base64.b64encode(bits).decode(),
            "eips": per_eip, "client_wide_failures": client_wide, "results": results,
        }
        del doc
        log(f"run   {client}: {version[:48]} {release} {row['ntests']} cases {row['fails']} fails")
    return runs


def snapshot(out_dir, log=print):
    eips_repo = sources.ensure_repo("EIPs.git", config.EIPS_REPO, f"+refs/heads/{config.EIPS_BRANCH}:refs/heads/{config.EIPS_BRANCH}")
    eels_repo = sources.ensure_repo("execution-specs.git", config.EELS_REPO, f"+refs/tags/{config.RELEASE_PREFIX}*:refs/tags/{config.RELEASE_PREFIX}*")
    tags = sources.git(eels_repo, "tag", "--list", f"{config.RELEASE_PREFIX}*").split()
    tag = index.newest_release(tags)
    log(f"eels  newest release {tag}")
    specs = collect_specs(eips_repo, eels_repo, tag, log)
    listing = sources.hive_listing()
    log(f"hive  listing.jsonl {len(listing)} rows")
    runs = collect_runs(listing, out_dir, log)
    return {
        "name": config.NAME, "fork": config.FORK,
        "taken_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "newest_release": tag, "release_commit": specs["tag_commit"], "release_date": specs["tag_date"],
        "release_url": f"{config.GITHUB}/{config.EELS_REPO}/releases/tag/{tag.replace('@', '%40')}",
        "listing_url": f"{config.HIVE}/listing.jsonl", "listing_rows": len(listing),
        "meta": {"eip": config.META_EIP, "name": config.META_NAME, "url": f"{config.GITHUB}/{config.EIPS_REPO}/blob/{config.EIPS_BRANCH}/EIPS/eip-{config.META_EIP}.md"},
        "eips": specs["eips"], "runs": runs,
    }


def write_snapshot(snap, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    slim = {**snap, "runs": {c: {k: v for k, v in r.items() if k != "results"} for c, r in snap["runs"].items()}}
    path = os.path.join(out_dir, f"{snap['taken_at'][:10]}.json")
    with open(path, "w") as f:
        json.dump(slim, f, indent=1, sort_keys=True)
    return path


def load_snapshot(path):
    snap = json.load(open(path))
    cases_dir = os.path.join(os.path.dirname(path), "cases")
    for run in snap["runs"].values():
        with gzip.open(os.path.join(cases_dir, f"{run['cases_hash']}.txt.gz")) as g:
            ids = g.read().decode().split("\n")
        bits = base64.b64decode(run["bitmap"])
        run["results"] = {t: bool(bits[i // 8] >> (i % 8) & 1) for i, t in enumerate(ids)}
    return snap
