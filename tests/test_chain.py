from eipproof import chain, index

NEWEST = "tests-bogota-devnet@v2.0.0"
SENDER = "tests/bogota/eip7906_transaction_assertions/test_txtrace.py::test_sender_nonce_change"


def run(release=NEWEST, passed=184, total=184, failed=(), results=None):
    return {"release": release, "image": "img", "version": "v", "url": "u",
            "eips": {"7906": {"total": total, "passed": passed, "failed": list(failed)}},
            "results": results or {}}


def eip_info(deltas=()):
    return {"head": "h" * 40, "pin": {"blob": "b" * 40, "commit": "p" * 40, "ambiguous": False},
            "deltas": list(deltas), "pending": []}


def snap(run_doc, info):
    return {"eips": {"7906": info}, "runs": {"nethermind": run_doc} if run_doc else {}, "newest_release": NEWEST}


def delta(commit="9099f412" + "0" * 32):
    return {"commit": commit, "candidates": []}


def test_pass_when_pin_equals_head_and_run_green():
    cell = chain.chain("7906", "nethermind", snap(run(), eip_info()), [])
    assert cell["headline"] == "pass"
    assert chain.headline_text(cell) == "pass 184/184"


def test_old_release_is_stale_even_if_green():
    cell = chain.chain("7906", "nethermind", snap(run(release="tests-bogota-devnet@v1.1.1", passed=299, total=305), eip_info()), [])
    assert cell["headline"] == "stale-release"
    assert cell["links"]["test"]["state"] == "n/a"
    assert chain.headline_text(cell) == "old tests v1.1.1"


def test_unattested_delta_is_open():
    cell = chain.chain("7906", "nethermind", snap(run(), eip_info([delta()])), [])
    assert cell["headline"] == "open"
    assert chain.headline_text(cell) == "1 spec change untested"


def test_attested_delta_with_passing_case_is_covered():
    results = {SENDER + "[fork_Bogota-state_test-keyed_True]": True, SENDER + "[fork_Bogota-state_test-keyed_False]": True}
    att = [{"eip": "7906", "commit": "9099f412", "killed": ["test_txtrace.py::test_sender_nonce_change"], "kind": "normative"}]
    cell = chain.chain("7906", "nethermind", snap(run(results=results), eip_info([delta()])), att)
    assert cell["links"]["test"]["deltas"][0]["state"] == "covered"
    assert cell["links"]["test"]["deltas"][0]["cases"] == 2
    assert cell["headline"] == "pass"


def test_hand_attestation_without_mutant_stays_open():
    results = {SENDER + "[fork_Bogota-keyed_True]": True}
    att = [{"eip": "7906", "commit": "9099f412", "tests": ["test_txtrace.py::test_sender_nonce_change"], "author": "x", "date": "d", "kind": "normative", "status": "draft"}]
    cell = chain.chain("7906", "nethermind", snap(run(results=results), eip_info([delta()])), att)
    assert cell["links"]["test"]["deltas"][0]["state"] == "open"
    assert cell["headline"] == "open"
    items = chain.queue([cell], ["7906"])
    assert [(i["kind"], i["action"]) for i in items] == [("open-delta", "run eipproof prove")]


def test_attested_delta_with_failing_case_fails():
    results = {SENDER + "[fork_Bogota-state_test-keyed_True]": False}
    att = [{"eip": "7906", "commit": "9099f412", "killed": ["test_txtrace.py::test_sender_nonce_change"], "kind": "normative"}]
    cell = chain.chain("7906", "nethermind", snap(run(results=results), eip_info([delta()])), att)
    assert cell["headline"] == "fail"


def test_proof_kill_ids_must_pass_in_the_run():
    killed = SENDER + "[fork_Bogota-blockchain_test_engine_from_state_test-keyed_nonce]"
    proof = [{"eip": "7906", "commit": "9099f412", "kind": "normative", "killed": [killed]}]
    green = chain.chain("7906", "nethermind", snap(run(results={killed: True}), eip_info([delta()])), proof)
    red = chain.chain("7906", "nethermind", snap(run(results={killed: False}), eip_info([delta()])), proof)
    assert (green["headline"], red["headline"]) == ("pass", "fail")


def test_surviving_mutant_keeps_delta_open():
    proof = [{"eip": "7906", "commit": "9099f412", "kind": "normative", "killed": []}]
    cell = chain.chain("7906", "nethermind", snap(run(), eip_info([delta()])), proof)
    assert cell["links"]["test"]["deltas"][0]["state"] == "mutant-survived"
    assert cell["headline"] == "open"
    assert chain.queue([cell], ["7906"])[0]["action"] == "write a test that kills the mutant"


def test_attested_test_missing_from_run_stays_open():
    att = [{"eip": "7906", "commit": "9099f412", "killed": ["test_txtrace.py::test_nope"], "kind": "normative"}]
    cell = chain.chain("7906", "nethermind", snap(run(), eip_info([delta()])), att)
    assert cell["links"]["test"]["deltas"][0]["state"] == "attested-not-run"
    assert cell["headline"] == "open"


def test_run_failure_outranks_open_delta():
    cell = chain.chain("7906", "nethermind", snap(run(passed=183, failed=["t"]), eip_info([delta()])), [])
    assert cell["headline"] == "fail"


def test_missing_run():
    cell = chain.chain("7906", "nethermind", snap(None, eip_info()), [])
    assert cell["headline"] == "no-run"


def test_param_selector_needs_subset():
    results = {SENDER + "[fork_Bogota-state_test-keyed_True]": True, SENDER + "[fork_Bogota-state_test-keyed_False]": False}
    assert list(chain.matching_cases("test_txtrace.py::test_sender_nonce_change[keyed_True]", results).values()) == [True]


def test_queue_merges_one_delta_across_clients():
    s = {"eips": {"7906": eip_info([delta()])}, "runs": {"nethermind": run(), "reth": run()}, "newest_release": NEWEST}
    cells = [chain.chain("7906", c, s, []) for c in ("nethermind", "reth")]
    items = chain.queue(cells, ["7906"])
    assert [(i["kind"], i["clients"]) for i in items] == [("open-delta", ["nethermind", "reth"])]


def test_pin_resolves_to_newest_eligible_revision():
    revs = [{"commit": "a", "blob": "x", "date": "2026-10-01T00:00:00Z", "order": 0},
            {"commit": "b", "blob": "y", "date": "2026-10-10T00:00:00Z", "order": 1},
            {"commit": "c", "blob": "x", "date": "2026-10-30T00:00:00Z", "order": 2}]
    pin = index.resolve_pin(revs, "x", "2026-10-27T00:00:00Z")
    assert pin == {"blob": "x", "commit": "a", "ambiguous": True}
    assert [r["commit"] for r in index.deltas_after(revs, "a")] == ["b", "c"]


def test_case_id_strips_client_suffix():
    assert index.case_id("t.py::f[fork_Bogota-x]-nethermind") == "t.py::f[fork_Bogota-x]"


def test_newest_release_is_numeric():
    assert index.newest_release(["tests-bogota-devnet@v1.10.0", "tests-bogota-devnet@v2.0.0", "tests-bogota-devnet@v1.9.9"]) == NEWEST


def test_infra_broken_runs_are_skipped():
    rows = [{"name": "eels/consume-engine", "clients": ["besu_default"], "ntests": 100, "fails": 90, "start": "2"},
            {"name": "eels/consume-engine", "clients": ["besu_default"], "ntests": 100, "fails": 1, "start": "1"}]
    assert index.pick_runs(rows)["besu"]["start"] == "1"


def test_delta_tokens_from_added_lines_only():
    diff = "--- a\n+++ b\n-old `nonces_changed`\n+new `slots_changed` and `APPROVE`\n"
    assert index.delta_tokens(diff) == ["slots_changed", "APPROVE"]
