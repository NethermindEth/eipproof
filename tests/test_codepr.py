import copy
import re
import subprocess

import pytest

from eipproof import build, cli, codepr, config, handoff, render
from tests.test_handoff import NOW, SNAP, fake_pulls, pull

BRANCH = "master"


def pr(state, merged=None, base=BRANCH, landed=None):
    row = {"number": 1, "title": "EIP-8250", "url": "u", "state": state, "merged": merged, "base": base}
    if landed is not None:
        row["landed"] = landed
    return row


@pytest.mark.parametrize("text,expected", [
    ("src/Nethermind/Nethermind.Core/Eip8250Constants.cs", True),
    ("// EIP-8250: keyed nonces", True),
    ("public bool IsEip8250Enabled => true;", True),
    ("see eip 8250 for details", True),
    ("crates/evm/src/eip_8250.rs", True),
    ("core/state/reader_eip_7928.go", False),
    ('"0x31206fa80a50bb6abe2908505082500000"', False),
    ("config/src/main/resources/hoodi.json", False),
    ("EIP-82501 is a different EIP", False),
    ("Cargo.lock", False),
    ("seip8250", False),
])
def test_names_eip_needs_the_eip_word_not_just_the_number(text, expected):
    assert codepr.names_eip(text, "8250") is expected


def test_two_named_files_on_the_default_branch_mean_implemented():
    assert codepr.status([], 2, [], BRANCH) == codepr.IMPLEMENTED


def test_one_named_file_is_not_enough():
    assert codepr.status([], 1, [], BRANCH) == codepr.NOT_STARTED


def test_merged_pr_into_default_branch_means_implemented():
    assert codepr.status([pr("merged", "2026-10-01T00:00:00Z")], 0, [], BRANCH) == codepr.IMPLEMENTED


def test_spec_change_after_last_merged_pr_means_stale():
    prs = [pr("merged", "2026-10-01T00:00:00Z"), pr("merged", "2026-10-20T00:00:00Z")]
    assert codepr.status(prs, 5, ["2026-10-27T11:42:30Z"], BRANCH) == codepr.STALE
    assert codepr.status(prs, 5, ["2026-10-19T00:00:00Z"], BRANCH) == codepr.IMPLEMENTED


def test_stale_compares_instants_across_time_zones():
    prs = [pr("merged", "2026-11-01T10:00:00Z")]
    assert codepr.status(prs, 0, ["2026-11-01T04:20:25-07:00"], BRANCH) == codepr.STALE
    assert codepr.status(prs, 0, ["2026-11-01T02:20:25-07:00"], BRANCH) == codepr.IMPLEMENTED


def test_open_pr_means_in_progress():
    assert codepr.status([pr("open")], 1, [], BRANCH) == codepr.IN_PROGRESS


def test_nothing_means_not_started():
    assert codepr.status([], 0, ["2026-10-27T11:42:30Z"], BRANCH) == codepr.NOT_STARTED


def test_pr_merged_into_a_feature_branch_counts_only_once_landed():
    unlanded = pr("merged", "2026-10-01T00:00:00Z", base="bogota", landed=False)
    assert codepr.status([unlanded], 0, [], BRANCH) == codepr.IN_PROGRESS
    assert codepr.status([{**unlanded, "landed": True}], 0, [], BRANCH) == codepr.IMPLEMENTED


def test_layer_picks_el_or_cl_clients():
    el = [c for c, m in config.CODE_CLIENTS.items() if m["layer"] == "el"]
    cl = [c for c, m in config.CODE_CLIENTS.items() if m["layer"] == "cl"]
    assert codepr.clients_for(codepr.eip_layer("7732", {"test_dir": None})) == cl
    assert codepr.clients_for(codepr.eip_layer("8141", {"test_dir": "tests/bogota/eip8141"})) == el
    assert codepr.clients_for(codepr.eip_layer("8261", {})) == el + cl
    assert {"lighthouse", "prysm", "lodestar", "nimbus", "grandine"} <= set(cl)


def test_editorial_attested_change_does_not_make_code_stale():
    info = {"eip": "7906", "deltas": [{"commit": "9099f412aa", "date": "2026-10-27T11:42:30Z"}, {"commit": "abcdef12aa", "date": "2026-10-28T00:00:00Z"}]}
    atts = [{"eip": "7906", "commit": "abcdef12", "kind": "editorial"}]
    assert codepr.normative_dates(info, atts) == ["2026-10-27T11:42:30Z"]


def fake_api(repos, compare):
    pulls, calls = fake_pulls(repos)

    def api(path):
        m = re.match(r"repos/([^/]+/[^/]+)/compare/[^.]+\.\.\.(\w+)", path)
        if m:
            return {"status": compare[m.group(2)]}
        return pulls(path)

    return api, calls


def merged_pull(number, title, merged_at, base, sha):
    return {**pull(number, title, state="closed", merged_at=merged_at), "base": {"ref": base}, "merge_commit_sha": sha}


def test_collect_reads_files_and_prs_per_layer(monkeypatch):
    monkeypatch.setattr(handoff, "LISTED", {})
    trees = {c: ["src/Eip8141Tx.cs", "src/eip8141/Validate.cs", "genesis/0x8141.json"] if c == "nethermind" else [] for c in config.CODE_CLIENTS}
    monkeypatch.setattr(codepr, "tree_files", lambda c, eips: ("c" * 40, trees[c], []))
    repos = {config.CODE_CLIENTS["go-ethereum"]["repo"]: [
        merged_pull(10, "core: EIP-8141 frames", "2026-10-30T00:00:00Z", "bogota", "a" * 40),
        merged_pull(11, "core: EIP-8141 validation", "2026-10-31T00:00:00Z", "bogota", "b" * 40),
    ], config.CODE_CLIENTS["reth"]["repo"]: [pull(12, "feat: EIP-8141")]}
    api, _ = fake_api(repos, {"a" * 40: "behind", "b" * 40: "diverged"})
    monkeypatch.setattr(handoff.sources, "gh_api", api)
    eips = {"8141": {"eip": "8141", "test_dir": "tests/bogota/eip8141", "deltas": []}, "7732": {"eip": "7732", "test_dir": None, "deltas": []}}
    out = codepr.collect(eips, log=lambda *_: None, now=NOW)
    assert set(out) == set(config.CODE_CLIENTS)
    assert set(out["nethermind"]["eips"]) == {"8141"} and set(out["lighthouse"]["eips"]) == {"7732"}
    snap = {"eips": eips, "code_status": out}
    status = {c["client"]: c["status"] for c in codepr.cells(snap, "8141")}
    assert status == {"nethermind": "implemented", "go-ethereum": "implemented", "reth": "in-progress", "ethrex": "not-started", "besu": "not-started"}
    geth = codepr.cell(snap, "go-ethereum", "8141")
    assert [p["state"] for p in geth["prs"]] == ["merged-elsewhere", "merged"]


def test_unreachable_client_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(handoff, "LISTED", {})

    def boom(client, eips):
        raise OSError("network")

    monkeypatch.setattr(codepr, "tree_files", boom)
    out = codepr.collect({"8141": {"eip": "8141", "test_dir": "x", "deltas": []}}, log=lambda *_: None, now=NOW)
    c = codepr.cell({"eips": {"8141": {"eip": "8141", "deltas": []}}, "code_status": out}, "nethermind", "8141")
    assert c["state"] == "unreachable" and codepr.evidence_text(c) == "lookup failed in this snapshot"


def code_block(snap, status_by_client):
    out = {}
    for client in config.CODE_CLIENTS:
        files = 3 if status_by_client.get(client) == "implemented" else 0
        out[client] = {"state": "ok", "repo": config.CODE_CLIENTS[client]["repo"], "branch": config.CODE_CLIENTS[client]["branch"],
                       "commit": "c" * 40, "truncated": False, "merged_since": "2026-09-01",
                       "eips": {eip: {"files": files, "paths": [], "prs": []} for eip in snap["eips"]}}
    return out


def test_code_signal_never_changes_a_test_verdict(tmp_path):
    snap = build.load_snapshot(SNAP)
    before = {(c["eip"], c["client"]): c["headline"] for c in cli.write_site(copy.deepcopy(snap), str(tmp_path / "a"))[0]}
    snap["code_status"] = code_block(snap, {c: "implemented" for c in config.CODE_CLIENTS})
    cells, _ = cli.write_site(snap, str(tmp_path / "b"))
    assert {(c["eip"], c["client"]): c["headline"] for c in cells} == before
    page = (tmp_path / "b" / render.eip_href("8141")).read_text()
    assert 'data-mark="code-status"' in page and 'data-mark="code-implemented"' in page and "Client PRs" not in page
    assert (tmp_path / "b" / "api" / "code.json").exists()
    assert "Code and PRs" not in (tmp_path / "a" / render.eip_href("8141")).read_text()


@pytest.mark.parametrize(("text", "expected"), [
    ("ePBS: process payload envelope", True),
    ("beacon_node/epbs/src/lib.rs", True),
    ("crates/epbsx/mod.rs", False),
    ("rename deepbs helper", False),
])
def test_known_alias_names_the_eip(text, expected):
    assert codepr.names(text, "7732") is expected
    assert codepr.names(text, "8141") is False


def git_tree(tmp_path, files):
    work = tmp_path / "work"
    for name, text in files.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(text)
    run = lambda *a: subprocess.run(["git", "-C", str(work), *a], check=True, capture_output=True, text=True).stdout
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "t")
    return str(work / ".git"), run("rev-parse", "HEAD").strip()


def test_files_whose_contents_name_the_eip_count(tmp_path):
    gitdir, commit = git_tree(tmp_path, {
        "core/vm/interpreter.go": "// EIP-7702: set code\nfunc run() {}\n",
        "core/types/tx_setcode.go": "if rules.IsPrague { applyEip7702(tx) }\n",
        "core/state.go": "func untouched() {}\n",
        "params/config.go": "seip7702 := 1\nEIP-77021\n",
    })
    hits = codepr.content_hits(gitdir, commit, ["7702"])
    paths = sorted(codepr.naming_files([], hits, "7702"))
    assert paths == ["core/types/tx_setcode.go", "core/vm/interpreter.go"]
    assert codepr.status([], len(paths), [], BRANCH) == codepr.IMPLEMENTED


def test_go_camel_case_upper_eip_counts(tmp_path):
    gitdir, commit = git_tree(tmp_path, {
        "core/vm/instructions_test.go": "func TestEIP8024_Execution(t *testing.T) {}\n",
        "params/config.go": "func (c *ChainConfig) IsEIP8024(num uint64) bool { return true }\n",
        "core/vm/jump.go": "seip8024 := 1\nXEIP8024\n",
    })
    hits = codepr.content_hits(gitdir, commit, ["8024"])
    paths = sorted(codepr.naming_files([], hits, "8024"))
    assert paths == ["core/vm/instructions_test.go", "params/config.go"]


def test_hex_lock_and_genesis_hits_are_dropped(tmp_path):
    gitdir, commit = git_tree(tmp_path, {
        "tests/blob.json": '"0x31206fa80a50bb6abe2908505082500000"\n',
        "Cargo.lock": 'name = "eip-8250"\n',
        "go.sum": "github.com/x/eip8250 v1\n",
        "config/genesis/hoodi.json": '{"eip8250Time": 0}\n',
        "src/Eip8250.cs": "class Eip8250 {}\n",
    })
    hits = codepr.content_hits(gitdir, commit, ["8250"])
    files = codepr.naming_files(["Cargo.lock", "src/Eip8250.cs"], hits, "8250")
    assert files == ["src/Eip8250.cs"]
    assert codepr.status([], len(files), [], BRANCH) == codepr.NOT_STARTED


def test_alias_in_contents_counts_for_cl_code(tmp_path):
    gitdir, commit = git_tree(tmp_path, {
        "beacon/a.rs": "// ePBS bid processing\n",
        "beacon/b.rs": "use crate::epbs::Envelope;\n",
        "beacon/c.rs": "fn deepbs() {}\n",
    })
    hits = codepr.content_hits(gitdir, commit, ["7732", "8141"])
    assert sorted(codepr.naming_files([], hits, "7732")) == ["beacon/a.rs", "beacon/b.rs"]
    assert codepr.naming_files([], hits, "8141") == []


def test_a_file_named_by_path_and_content_counts_once():
    hits = [("src/Eip8141Tx.cs", "Eip8141"), ("src/Eip8141Tx.cs", "EIP-8141"), ("src/Other.cs", "EIP-8141")]
    assert codepr.naming_files(["src/Eip8141Tx.cs", "src/Plain.cs"], hits, "8141") == ["src/Eip8141Tx.cs", "src/Other.cs"]


def test_spec_revision_without_tests_still_makes_code_stale():
    info = {"eip": "7732", "test_dir": None, "deltas": [], "revisions": [
        {"commit": "aa11", "date": "2026-09-01T00:00:00Z"}, {"commit": "bb22", "date": "2026-10-30T00:00:00Z"}]}
    prs = [{"state": "merged", "merged": "2026-10-01T00:00:00Z", "base": "unstable"}]
    assert codepr.status(prs, 0, codepr.normative_dates(info, []), "unstable") == codepr.STALE
