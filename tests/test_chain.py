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


def test_meta_stages_reads_headings_and_list_items():
    text = ("## Specification\n\n### EIPs Scheduled for Inclusion\n\n* [EIP-8141](./eip-8141.md): Frame\n\n"
            "### Considered for Inclusion\n\n* [EIP-7906](./eip-7906.md): Assertions\n\n#### Core\n\n* [EIP-8250](./eip-8250.md): Nonces\n\n"
            "### Proposed for Inclusion\n\n* [EIP-7907](./eip-7907.md): Code size\n\n## Rationale\n\n* [EIP-1](./eip-1.md): x\n")
    assert index.meta_stages(text) == {"8141": ["Scheduled"], "7906": ["Considered"], "8250": ["Considered"], "7907": ["Proposed"]}


def test_frontmatter_title_and_status():
    text = "---\neip: 7906\ntitle: Transaction Assertions via State Diff Opcode\nstatus: Draft\ntype: Standards Track\n---\n\n## Abstract\n"
    assert index.frontmatter(text) == {"title": "Transaction Assertions via State Diff Opcode", "status": "Draft"}


def test_constant_changes_from_table_rows():
    diff = ("--- a\n+++ b\n-| `PER_AUTH_BASE_COST`     | `15000`  |\n+| `PER_AUTH_BASE_COST`     | `12500` |\n"
            "-| `KEYED_NONCE_FIRST_USE_GAS` | `20000` |\n+| `NEW_LIMIT` | `16` |\n | `UNCHANGED_VALUE` | `1` |\n")
    assert index.constant_changes(diff) == [
        {"name": "KEYED_NONCE_FIRST_USE_GAS", "before": ["20000"], "after": []},
        {"name": "NEW_LIMIT", "before": [], "after": ["16"]},
        {"name": "PER_AUTH_BASE_COST", "before": ["15000"], "after": ["12500"]},
    ]


def test_constant_changes_from_python_assignments():
    diff = "--- a\n+++ b\n-MAX_KEYS = 8\n+MAX_KEYS = 16\n+prose with `SOME_NAME` only\n"
    assert index.constant_changes(diff) == [{"name": "MAX_KEYS", "before": ["8"], "after": ["16"]}]


def test_rows_are_sfi_cfi_with_sfi_first_then_tested():
    stages = {"7805": ["Scheduled"], "8141": ["Scheduled"], "7906": ["Considered"], "3298": ["Considered"], "9999": ["Proposed"], "1111": ["Declined"]}
    assert sorted(index.listed_eips(stages), key=int) == ["3298", "7805", "7906", "8141"]
    eips = {e: {"stage": stages[e], "test_dir": None if e in ("7805", "3298") else "d"} for e in ("7805", "8141", "7906", "3298")}
    assert index.row_order(eips) == ["8141", "7805", "7906", "3298"]


def history(*moves):
    return [{"commit": c * 40, "date": "2026-10-27T18:11:18Z", "subject": f"s (#{pr})", "pr": pr, "blob": blob, "files": ["test_x.py"],
             "release": rel, "superseded": rel is None} for c, pr, blob, rel in moves]


def test_pr_number_comes_from_squash_subject():
    assert index.pr_number("feat(tests): apply EIP-7906 changes (#3895)") == 3895
    assert index.pr_number("chore: bump") is None


def test_rev_tests_names_the_pin_move_release_and_the_clients_that_ran_it():
    info = {"pin": {"commit": "p"}, "deltas": [{"commit": "d"}],
            "pin_history": history(("1", 3730, "old", None), ("2", 3895, "new", NEWEST))}
    runs = {"go-ethereum": {"release": NEWEST}, "besu": {"release": "tests-bogota-devnet@v1.1.1"}, "reth": None}
    pinned = index.rev_tests({"commit": "p", "blob": "new"}, info, runs)
    assert (pinned["state"], pinned["move"]["pr"], pinned["ran"]) == ("pinned", 3895, ["go-ethereum"])
    assert index.rev_tests({"commit": "o", "blob": "old"}, info, runs)["state"] == "superseded"
    assert index.rev_tests({"commit": "d", "blob": "head"}, info, runs)["state"] == "waiting"
    assert index.rev_tests({"commit": "x", "blob": "gone"}, info, runs)["state"] == "never"


def test_rev_tests_credits_a_release_on_a_side_branch():
    info = {"pin": {"commit": "p"}, "deltas": [], "release_pins": {"tests-bogota-devnet@v1.1.1": "old", NEWEST: "new"},
            "pin_history": history(("1", 3730, "old", None), ("2", 3895, "new", NEWEST))}
    runs = {"go-ethereum": {"release": NEWEST}, "besu": {"release": "tests-bogota-devnet@v1.1.1"}}
    old = index.rev_tests({"commit": "o", "blob": "old"}, info, runs)
    assert (old["state"], old["release"], old["ran"]) == ("pinned", "tests-bogota-devnet@v1.1.1", ["besu"])
    side = index.rev_tests({"commit": "s", "blob": "side"}, {**info, "release_pins": {"tests-bogota-devnet@v1.1.0": "side"}}, runs)
    assert (side["state"], side["move"], side["release"]) == ("pinned", None, "tests-bogota-devnet@v1.1.0")


def test_client_cells_get_fix_or_run_and_spec_work_goes_to_eels():
    s = {"eips": {"7906": eip_info([delta()])}, "runs": {"nethermind": run(passed=183, failed=["t"]), "reth": run(), "besu": run(release="tests-bogota-devnet@v1.1.1")},
         "newest_release": NEWEST}
    cells = {c: chain.chain("7906", c, s, []) for c in ("nethermind", "reth", "besu", "ethrex")}
    assert {c: chain.cell_action(v, NEWEST) for c, v in cells.items()} == {"nethermind": "fix client", "reth": None, "besu": "run v2.0.0", "ethrex": "run v2.0.0"}
    assert chain.eels_action(list(cells.values())) == ("write test", 1)
    items = chain.queue(list(cells.values()), ["7906"])
    assert {(i["kind"], i["owner"]) for i in items} == {("run-fail", "nethermind"), ("open-delta", "eels"), ("stale-release", "besu")}


def test_surviving_mutant_is_named_in_the_eels_action():
    proof = [{"eip": "7906", "commit": "9099f412", "kind": "normative", "killed": []}]
    cell = chain.chain("7906", "nethermind", snap(run(), eip_info([delta()])), proof)
    assert chain.eels_action([cell]) == ("mutant uncovered", 1)
    assert chain.eels_action([chain.chain("7906", "nethermind", snap(run(), eip_info()), [])]) == (None, 0)
