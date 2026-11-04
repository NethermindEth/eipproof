import re

SEVERITY = ["fail", "no-run", "stale-release", "no-tests", "open", "pass"]
EELS = "eels"
OPEN_DELTA = ("open", "attested-not-run", "mutant-survived")

_CASE = re.compile(r"^(?P<file>[^:]+)::(?P<func>[A-Za-z0-9_]+)(?:\[(?P<params>.*)\])?$")


def parse_case(test_id):
    m = _CASE.match(test_id)
    if not m:
        return None
    params = m.group("params")
    return m.group("file"), m.group("func"), set(params.split("-")) if params else set()


def matching_cases(selector, results):
    want = parse_case(selector)
    if want is None:
        return {}
    file, func, params = want
    hits = {}
    for test_id, passed in results.items():
        got = parse_case(test_id)
        if got and got[1] == func and got[0].endswith(file) and params <= got[2]:
            hits[test_id] = passed
    return hits


def run_link(run, eip, newest_release):
    if run is None:
        return {"state": "no-run"}
    cases = run["eips"].get(eip, {"total": 0, "passed": 0, "failed": []})
    base = {
        "release": run["release"],
        "image": run["image"],
        "version": run["version"],
        "url": run["url"],
        "total": cases["total"],
        "passed": cases["passed"],
        "failed": cases["failed"],
    }
    if run["release"] != newest_release:
        return {**base, "state": "stale-release", "newest_release": newest_release}
    if cases["total"] == 0:
        return {**base, "state": "no-tests"}
    if cases["failed"]:
        return {**base, "state": "fail"}
    return {**base, "state": "pass"}


def delta_state(delta, attestations, results):
    mine = [a for a in attestations if delta["commit"].startswith(str(a["commit"]))]
    if not mine:
        return {"state": "open"}
    att = mine[-1]
    if att.get("kind") == "editorial":
        return {"state": "editorial", "attestation": att}
    if "killed" not in att:
        return {"state": "open", "attestation": att}
    selectors = att["killed"]
    if not selectors:
        return {"state": "mutant-survived", "attestation": att}
    hits = {}
    for selector in selectors:
        found = matching_cases(selector, results)
        if not found:
            return {"state": "attested-not-run", "attestation": att, "missing": selector}
        hits.update(found)
    if not all(hits.values()):
        return {"state": "attested-failed", "attestation": att, "failed": sorted(k for k, v in hits.items() if not v)}
    return {"state": "covered", "attestation": att, "cases": len(hits)}


def candidate_results(delta, results):
    out = []
    for cand in delta.get("candidates", []):
        hits = matching_cases(cand["test"], results)
        out.append({**cand, "cases": len(hits), "passed": sum(hits.values())})
    return out


def test_link(eip_info, run, newest_release, attestations):
    if run is None or run["release"] != newest_release:
        return {"state": "n/a", "deltas": []}
    deltas = []
    for delta in eip_info["deltas"]:
        st = delta_state(delta, attestations, run["results"])
        st["commit"] = delta["commit"]
        st["candidates"] = candidate_results(delta, run["results"]) if st["state"] == "open" else []
        deltas.append(st)
    states = {d["state"] for d in deltas}
    if "attested-failed" in states:
        state = "fail"
    elif states & {"open", "attested-not-run", "mutant-survived"}:
        state = "open"
    else:
        state = "pass"
    return {"state": state, "deltas": deltas, "open": sum(d["state"] in ("open", "attested-not-run", "mutant-survived") for d in deltas)}


def spec_link(eip_info):
    pin = eip_info["pin"]
    return {
        "state": "pass" if not eip_info["deltas"] else "open",
        "head": eip_info["head"],
        "pin_blob": pin["blob"],
        "pin_commit": pin["commit"],
        "pin_ambiguous": pin["ambiguous"],
        "behind": len(eip_info["deltas"]),
        "pending": eip_info["pending"],
    }


def chain(eip, client, snap, attestations):
    eip_info = snap["eips"][eip]
    run = snap["runs"].get(client)
    newest = snap["newest_release"]
    links = {
        "spec": spec_link(eip_info),
        "test": test_link(eip_info, run, newest, [a for a in attestations if a["eip"] == eip]),
        "run": run_link(run, eip, newest),
    }
    if links["spec"]["state"] == "open" and links["test"]["state"] == "pass":
        links["spec"]["state"] = "covered"
    headline = weakest(links)
    return {"eip": eip, "client": client, "headline": headline, "links": links}


def weakest(links):
    run_state = links["run"]["state"]
    if run_state in ("fail", "no-run", "stale-release", "no-tests"):
        return run_state
    if links["test"]["state"] == "fail":
        return "fail"
    if links["test"]["state"] == "open":
        return "open"
    return "pass"


def headline_text(cell):
    h = cell["headline"]
    run = cell["links"]["run"]
    if h == "pass":
        return f"pass {run['passed']}/{run['total']}"
    if h == "fail":
        if run["state"] == "fail":
            return f"fail {run['passed']}/{run['total']}"
        return "proof test fails"
    if h == "stale-release":
        return f"old tests {release_short(run['release'])}"
    if h == "open":
        n = cell['links']['test']['open']
        return f"{n} spec change{'s' if n > 1 else ''} untested"
    if h == "no-tests":
        return "no tests in run"
    return "no run"


def release_short(release):
    return release.split("@", 1)[-1] if release else "?"


def cell_action(cell, newest_release):
    h = cell["headline"]
    if h == "fail":
        return "fix client"
    if h in ("stale-release", "no-run"):
        return f"run {release_short(newest_release)}"
    return None


def eels_action(cells):
    states = {d["commit"]: d["state"] for c in cells for d in c["links"]["test"]["deltas"] if d["state"] in OPEN_DELTA}
    if not states:
        return None, 0
    verb = "mutant uncovered" if "mutant-survived" in states.values() else "write test"
    return verb, len(states)


def queue(cells, row_order):
    items = []
    seen_deltas = {}
    for cell in cells:
        rank = row_order.index(cell["eip"]) if cell["eip"] in row_order else len(row_order)
        h = cell["headline"]
        if h == "fail":
            items.append({"kind": "run-fail", "eip": cell["eip"], "clients": [cell["client"]], "owner": cell["client"], "rank": rank,
                          "failed": cell["links"]["run"]["failed"], "action": "fix client or report test"})
        elif h == "stale-release":
            items.append({"kind": "stale-release", "eip": cell["eip"], "clients": [cell["client"]], "owner": cell["client"], "rank": rank,
                          "release": cell["links"]["run"]["release"], "action": f"run {release_short(cell['links']['run']['newest_release'])}"})
        for d in cell["links"]["test"]["deltas"]:
            if d["state"] in OPEN_DELTA:
                key = (cell["eip"], d["commit"])
                item = seen_deltas.get(key)
                if item is None:
                    item = {"kind": "open-delta", "eip": cell["eip"], "commit": d["commit"], "clients": [], "owner": EELS, "rank": rank,
                            "candidates": {}, "action": "write a test that kills the mutant" if d["state"] == "mutant-survived" else "run eipproof prove"}
                    seen_deltas[key] = item
                    items.append(item)
                item["clients"].append(cell["client"])
                for c in d["candidates"]:
                    item["candidates"].setdefault(c["test"], {})[cell["client"]] = (c["passed"], c["cases"])
    kind_rank = {"run-fail": 0, "open-delta": 1, "stale-release": 2}
    items.sort(key=lambda i: (i["rank"], kind_rank[i["kind"]], -len(i["clients"])))
    return items
