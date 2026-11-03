import ast
import hashlib
import re
from datetime import datetime, timedelta

from . import config

_EIP_DIR = re.compile(r"^" + re.escape(config.TEST_ROOT) + r"/eip(\d+)_[^/]+/")
_PIN = re.compile(r"ref_spec_(\d+)\s*=\s*ReferenceSpec\(\s*(?:git_path=)?\"(EIPS/eip-\d+\.md)\",\s*(?:version=)?\"([0-9a-f]{40})\"", re.S)
_RELEASE = re.compile(r"fixtures release: (\S+)")
_TICK = re.compile(r"`([^`]+)`")


def iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def release_key(tag):
    return tuple(int(x) for x in re.findall(r"\d+", tag.split("@", 1)[1]))


def newest_release(tags):
    return max((t for t in tags if t.startswith(config.RELEASE_PREFIX)), key=release_key)


def parse_pins(spec_py):
    return {num: {"path": path, "blob": blob} for num, path, blob in _PIN.findall(spec_py)}


def resolve_pin(revisions, blob, cutoff):
    hits = [r for r in revisions if r["blob"] == blob]
    eligible = [r for r in hits if iso(r["date"]) <= iso(cutoff)]
    chosen = max(eligible, key=lambda r: r["order"], default=None)
    return {"blob": blob, "commit": chosen["commit"] if chosen else None, "ambiguous": len(hits) > 1}


def deltas_after(revisions, pin_commit):
    ordered = sorted(revisions, key=lambda r: r["order"])
    if pin_commit is None:
        return ordered
    idx = next(i for i, r in enumerate(ordered) if r["commit"] == pin_commit)
    return ordered[idx + 1:]


def delta_tokens(diff):
    added, removed = [], []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    toks = []
    for t in _TICK.findall("\n".join(added)):
        if t not in toks:
            toks.append(t)
    return toks


def test_functions(source):
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            out[node.name] = ast.get_source_segment(source, node)
    return out


def score_candidates(tokens, files):
    scored = []
    for path, source in files.items():
        for func, body in test_functions(source).items():
            low = body.lower()
            hit = [t for t in tokens if t.lower() in low]
            if hit:
                scored.append({"test": f"{path.rsplit('/', 1)[-1]}::{func}", "path": path, "score": len(hit), "tokens": hit})
    scored.sort(key=lambda c: (-c["score"], c["test"]))
    best = scored[0]["score"] if scored else 0
    return [c for c in scored if c["score"] == best]


def in_window(delta_date, author_date, days=config.CANDIDATE_WINDOW_DAYS):
    return abs(iso(author_date) - iso(delta_date)) <= timedelta(days=days)


def case_id(name):
    head, sep, tail = name.rpartition("]-")
    if sep:
        return head + "]"
    return name.rsplit("-", 1)[0]


def eip_of(test_id):
    m = _EIP_DIR.match(test_id)
    return m.group(1) if m else None


def summarize_cases(test_cases):
    results = {}
    for case in test_cases.values():
        summary = case["summaryResult"]
        passed = summary["pass"] if isinstance(summary, dict) else "'pass': True" in summary
        results[case_id(case["name"])] = bool(passed)
    per_eip = {}
    for test_id, passed in results.items():
        eip = eip_of(test_id)
        if eip is None:
            continue
        slot = per_eip.setdefault(eip, {"total": 0, "passed": 0, "failed": []})
        slot["total"] += 1
        slot["passed"] += passed
        if not passed:
            slot["failed"].append(test_id)
    client_wide = sorted(t for t, p in results.items() if not p and eip_of(t) is None)
    return results, per_eip, client_wide


def release_from_simlog(text):
    m = _RELEASE.search(text)
    return m.group(1) if m else None


def image_of(meta):
    clients = meta.get("clientConfig", {}).get("content", {}).get("clients", [])
    if not clients:
        return None
    args = clients[0].get("build_args", {})
    base = args.get("baseimage", "").rsplit("/", 2)
    return f"{'/'.join(base[-2:])}:{args.get('tag', '')}"


def commit_of(version):
    m = re.search(r"(?:\+|-)([0-9a-f]{7,40})(?:[/-]|$)", version)
    return m.group(1) if m else None


def pick_runs(listing):
    best = {}
    for row in listing:
        if row["name"] != config.SIMULATOR or not row["clients"]:
            continue
        client = row["clients"][0].rsplit("_", 1)[0]
        if client not in config.CLIENTS or row["ntests"] == 0:
            continue
        if row["fails"] / row["ntests"] > config.INFRA_FAIL_RATIO:
            continue
        if client not in best or row["start"] > best[client]["start"]:
            best[client] = row
    return best


def bitmap(results):
    ids = sorted(results)
    bits = bytearray((len(ids) + 7) // 8)
    for i, t in enumerate(ids):
        if results[t]:
            bits[i // 8] |= 1 << (i % 8)
    ids_blob = "\n".join(ids).encode()
    return hashlib.sha256(ids_blob).hexdigest(), ids_blob, bytes(bits)
