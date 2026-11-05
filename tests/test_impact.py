import json
import os
import re
import subprocess
import sys

import pytest
import yaml

from eipproof import build, cli, config, impact, render, sitecheck

SNAP = os.path.join(cli.ROOT, "snapshots", "2026-11-03.json")
ACTION = os.path.join(cli.ROOT, ".github", "actions", "pr-impact", "action.yml")

SPEC_8141 = """
| `FRAME_TX_TYPE`            | `0x06`            |
| `ENTRY_POINT`              | `address(0xaa)`   |
| `MAX_FRAMES`               | `64`              |
| `TX_MAX_GAS_LIMIT` | `16,777,216` | [EIP-7825](./eip-7825.md) |
| `CPSB` | `1,530` | [EIP-8037](./eip-8037.md) |
| `MAX_VERIFY_GAS`   | `100_000`  | Maximum amount of gas a node should expend validating signatures |
"""
SPEC_7906 = "| `ASSERT_EXEMPT_FLAG` | `0x04` |\n"
TEXTS = {"8141": SPEC_8141, "7906": SPEC_7906}


def pr(number=15000, title="fix(txpool): tighten admission", body="", sha="a" * 40):
    return {"number": number, "title": title, "body": body, "html_url": f"https://github.com/NethermindEth/nethermind/pull/{number}",
            "draft": False, "state": "open", "updated_at": "2026-11-04T10:00:00Z", "head": {"sha": sha}}


def file(path, patch=None, previous=None):
    out = {"filename": path, "status": "modified"}
    if patch is not None:
        out["patch"] = patch
    if previous:
        out["previous_filename"] = previous
    return out


def kinds(found, eip):
    return sorted({e["kind"] for e in found.get(eip, [])})


def test_mentions_accept_eip_words_and_camel_case_but_not_longer_numbers():
    tracked = {"7906", "8141"}
    assert impact.mentions("feat(eip7906): POST_TX flag", tracked) == {"7906"}
    assert impact.mentions("EIP-8141 and EIP 7906", tracked) == {"7906", "8141"}
    assert impact.mentions("if (spec.IsEip8141Enabled) Eip8141Constants.MaxFrames", tracked) == {"8141"}
    assert impact.mentions("src/Nethermind/Nethermind.Evm.Test/Eip8141ScenarioTests.cs", tracked) == {"8141"}
    assert impact.mentions("tests/bogota/eip8141_frame_transactions", tracked) == {"8141"}
    assert impact.mentions("EIP-79060 and seip7906 and #8141", tracked) == set()
    assert impact.mentions("EIP-7825 cap", tracked) == set()


def test_spec_constants_skip_rows_owned_by_another_eip():
    assert impact.spec_constants(SPEC_8141, "8141") == ["ENTRY_POINT", "FRAME_TX_TYPE", "MAX_FRAMES", "MAX_VERIFY_GAS"]


def test_spec_constants_skip_single_word_rows():
    text = "| `SSTORE` | `0x55` |\n| `SECP256K1N` | `0xff` |\n| `MAX_FRAMES` | `64` |\n"
    assert impact.spec_constants(text, "7928") == ["MAX_FRAMES"]


def test_constant_forms_add_pascal_case_only_for_three_part_names():
    assert impact.forms("MAX_VERIFY_GAS") == ["MAX_VERIFY_GAS", "MaxVerifyGas"]
    assert impact.forms("ENTRY_POINT") == ["ENTRY_POINT"]


def test_evidence_names_each_signal_with_its_source():
    consts = {e: impact.spec_constants(t, e) for e, t in TEXTS.items()}
    files = [file("src/Nethermind/Nethermind.TxPool/Filters/FrameTxVerifyGasFilter.cs",
                  "@@ -1,3 +1,3 @@\n-    long cap = 90_000;\n+    long cap = Eip8141Constants.MaxVerifyGas;\n context EntryPoint\n"),
             file("src/Nethermind/Nethermind.Core/Eip7906Flags.cs", previous="src/Nethermind/Nethermind.Core/Old.cs")]
    commits = [{"sha": "b" * 40, "commit": {"message": "refactor(eip7906): rename POST_TX_EXEMPT\n\nbody"}}]
    found = impact.evidence(pr(body="Spec: EIP-8141 mempool rules"), files, commits, consts)
    assert kinds(found, "8141") == ["body", "code", "constant"]
    assert kinds(found, "7906") == ["commit", "path"]
    const = next(e for e in found["8141"] if e["kind"] == "constant")
    assert const == {"kind": "constant", "name": "MAX_VERIFY_GAS", "as": "MaxVerifyGas",
                     "file": "src/Nethermind/Nethermind.TxPool/Filters/FrameTxVerifyGasFilter.cs"}
    assert not any(e.get("name") == "ENTRY_POINT" for e in found["8141"])


def test_context_lines_and_unrelated_prs_give_no_evidence():
    consts = {e: impact.spec_constants(t, e) for e, t in TEXTS.items()}
    files = [file("src/Nethermind/Nethermind.Evm/Tracing/Foo.cs", "@@ -1 +1 @@\n Eip8141Constants.MaxVerifyGas\n-a\n+b\n")]
    assert impact.evidence(pr(), files, [], consts) == {}


def gh_fake(pull, files, commits, pages_seen=None):
    def fake(path):
        if pages_seen is not None:
            pages_seen.append(path)
        if re.fullmatch(r"repos/NethermindEth/nethermind/pulls/\d+", path):
            return pull
        m = re.fullmatch(r"repos/NethermindEth/nethermind/pulls/\d+/(files|commits)\?per_page=100&page=(\d+)", path)
        assert m, path
        rows = files if m.group(1) == "files" else commits
        page = int(m.group(2))
        return rows[(page - 1) * 100:page * 100]
    return fake


def test_fetch_pr_pages_files_and_flags_the_github_cap(monkeypatch):
    many = [file(f"f{i}.cs", "+x\n") for i in range(250)]
    seen = []
    monkeypatch.setattr(impact.sources, "gh_api", gh_fake(pr(), many, [], seen))
    got = impact.fetch_pr("NethermindEth/nethermind", 15000, max_file_pages=2)
    assert len(got["files"]) == 200 and got["files_truncated"]
    assert sum("/files?" in p for p in seen) == 2
    got = impact.fetch_pr("NethermindEth/nethermind", 15000)
    assert len(got["files"]) == 250 and not got["files_truncated"]


def site_api(tmp_path):
    snap = build.load_snapshot(SNAP)
    snap["source"] = "live"
    cli.write_site(snap, str(tmp_path))
    return tmp_path


@pytest.fixture(scope="module")
def site_root(tmp_path_factory):
    return site_api(tmp_path_factory.mktemp("impact-site"))


def test_report_joins_evidence_with_spec_tests_and_the_client_cell(site_root, monkeypatch):
    monkeypatch.setattr(impact, "spec_text", lambda eip, head: TEXTS.get(eip, ""))
    pull = pr(14423, "feat(eip7906): POST_TX_EXEMPT frame flag", sha="c" * 40)
    files = [file("src/Nethermind/Nethermind.Core/FrameTxValidation.cs", "+ if (spec.IsEip8141Enabled)\n")]
    monkeypatch.setattr(impact.sources, "gh_api", gh_fake(pull, files, []))
    doc = impact.report("NethermindEth/nethermind", 14423, impact.local_site(str(site_root)))
    assert doc["client"] == "nethermind" and doc["state"] == "ok"
    rows = {r["eip"]: r for r in doc["eips"]}
    assert sorted(rows) == ["7906", "8141"]
    r = rows["8141"]
    assert r["fork"] == "bogota" and r["cell"]["client"] == "nethermind"
    assert r["cell"]["text"] and r["spec"]["head"] and r["spec"]["behind"] is not None
    assert r["page"].endswith("index.html#8141-nethermind")
    text = impact.markdown(doc)
    assert "EIP-7906" in text and "EIP-8141" in text and "#14423" in text
    assert "`IsEip8141Enabled`" not in text or "code" in text
    assert "<" not in re.sub(r"<!--.*?-->", "", text).replace("<br>", "")


def test_report_for_a_repo_that_is_not_a_tracked_client_has_no_cell(site_root, monkeypatch):
    monkeypatch.setattr(impact, "spec_text", lambda eip, head: "")
    pull = pr(1, "EIP-8141 notes")
    pull["html_url"] = "https://github.com/x/y/pull/1"
    monkeypatch.setattr(impact.sources, "gh_api", lambda path: pull if path.endswith("/pulls/1") else [])
    doc = impact.report("x/y", 1, impact.local_site(str(site_root)))
    assert doc["client"] is None
    assert [r["eip"] for r in doc["eips"]] == ["8141"] and doc["eips"][0]["cell"] is None


def test_unreachable_site_is_reported_not_hidden(monkeypatch):
    monkeypatch.setattr(impact.sources, "gh_api", lambda path: pr(1, "EIP-8141 x") if path.endswith("/pulls/1") else [])

    def down(path):
        raise OSError("down")

    doc = impact.report("NethermindEth/nethermind", 1, down)
    assert doc["state"] == "site-unreachable" and doc["eips"] == []
    assert "could not read" in impact.markdown(doc)


def test_titles_are_escaped_in_markdown():
    assert impact.md_text("x | y <script> [a](b)\nz") == "x \\| y &lt;script&gt; \\[a\\](b) z"


def test_cli_writes_markdown_and_json(site_root, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(impact, "spec_text", lambda eip, head: TEXTS.get(eip, ""))
    monkeypatch.setattr(impact.sources, "gh_api", gh_fake(pr(12612, "EIP-8141: canonical paymaster"), [], []))
    out = tmp_path / "impact.json"
    impact.main(["NethermindEth/nethermind", "12612", "--site", str(site_root), "--json", str(out)])
    assert "EIP-8141" in capsys.readouterr().out
    assert [r["eip"] for r in json.loads(out.read_text())["eips"]] == ["8141"]


def test_cli_subcommand_delegates(monkeypatch):
    seen = []
    monkeypatch.setattr(impact, "main", lambda argv: seen.append(argv))
    cli.main(["pr-impact", "NethermindEth/nethermind", "1", "--site", "x"])
    assert seen == [["NethermindEth/nethermind", "1", "--site", "x"]]


def test_impact_module_runs_without_pyyaml(tmp_path):
    stub = tmp_path / "yaml.py"
    stub.write_text("raise ImportError('no yaml')\n")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), cli.ROOT])}
    r = subprocess.run([sys.executable, "-m", "eipproof.impact", "--help"], capture_output=True, text=True, env=env, cwd=cli.ROOT)
    assert r.returncode == 0, r.stderr


def snap_with_impact(prs_block):
    snap = build.load_snapshot(SNAP)
    snap["source"] = "live"
    snap["pr_impact"] = prs_block
    return snap


def test_collect_checks_open_prs_and_reuses_unchanged_heads(monkeypatch):
    pulls = [pr(1, "EIP-8141 a", sha="1" * 40), pr(2, "docs: readme", sha="2" * 40), pr(3, "chore", sha="3" * 40)]
    calls = []

    def fake(path):
        calls.append(path)
        if "/pulls?state=open" in path:
            return pulls if path.endswith("page=1") else []
        if "/files?" in path:
            return [file("src/Eip7906Flags.cs")] if "/pulls/2/" in path else []
        raise AssertionError(path)

    monkeypatch.setattr(impact.handoff, "LISTED", {})
    monkeypatch.setattr(impact, "CHECKED", {})
    monkeypatch.setattr(impact.sources, "gh_api", fake)
    block = impact.collect("NethermindEth/nethermind", {"8141": "", "7906": ""}, log=lambda *_: None, limit=2)
    by = {p["number"]: p for p in block["prs"]}
    assert block["state"] == "ok" and block["unchecked"] == 1
    assert sorted(by) == [1, 2]
    assert sorted(by[1]["evidence"]) == ["8141"] and sorted(by[2]["evidence"]) == ["7906"]
    before = len(calls)
    impact.collect("NethermindEth/nethermind", {"8141": "", "7906": ""}, log=lambda *_: None, limit=2)
    assert len(calls) == before


def test_prs_page_lists_open_prs_with_evidence_and_cells(tmp_path):
    block = {"repo": "NethermindEth/nethermind", "client": "nethermind", "state": "ok", "unchecked": 0, "truncated": False, "checked": 2,
             "prs": [{"number": 14423, "title": "feat(eip7906): <b>flag</b>", "url": "https://github.com/NethermindEth/nethermind/pull/14423",
                      "draft": True, "updated": "2026-11-04", "head": "c" * 40, "files_truncated": False,
                      "evidence": {"7906": [{"kind": "title"}], "8141": [{"kind": "constant", "name": "MAX_VERIFY_GAS", "as": "MaxVerifyGas", "file": "a.cs"}]}}]}
    snap = snap_with_impact(block)
    cli.write_site(snap, str(tmp_path))
    page = (tmp_path / "prs.html").read_text()
    assert "#14423" in page and "&lt;b&gt;flag" in page and "<b>flag" not in page
    assert 'href="index.html#7906-nethermind"' in page and 'href="index.html#8141-nethermind"' in page
    assert "MAX_VERIFY_GAS" in page and "draft" in page
    doc = json.loads((tmp_path / "api" / "prs.json").read_text())
    assert doc["state"] == "ok" and doc["prs"][0]["eips"][0]["cell"]["client"] == "nethermind"
    assert 'href="prs.html"' in (tmp_path / "index.html").read_text()
    assert sitecheck.check_dir(str(tmp_path)) == []


def test_prs_page_says_not_collected_on_a_snapshot_build(tmp_path):
    snap = build.load_snapshot(SNAP)
    snap["source"] = "snapshot"
    cli.write_site(snap, str(tmp_path))
    assert "not collected" in (tmp_path / "prs.html").read_text()
    assert json.loads((tmp_path / "api" / "prs.json").read_text())["state"] == "not-collected"


def test_unreachable_pr_list_is_shown_as_unreachable(tmp_path):
    cli.write_site(snap_with_impact({"repo": "NethermindEth/nethermind", "client": "nethermind", "state": "unreachable", "reason": "OSError", "prs": []}),
                   str(tmp_path))
    assert "could not be listed" in (tmp_path / "prs.html").read_text()


def test_action_writes_only_the_job_summary_and_pins_nothing_unpinned():
    doc = yaml.safe_load(open(ACTION))
    assert doc["runs"]["using"] == "composite"
    steps = doc["runs"]["steps"]
    assert not any("uses" in s for s in steps)
    script = "\n".join(s.get("run", "") for s in steps)
    assert "GITHUB_STEP_SUMMARY" in script and "eipproof.impact" in script
    assert not re.search(r"gh (pr|issue) (comment|review|edit)|/comments", script)
    for s in steps:
        if "run" in s:
            assert "${{" not in s["run"], s["run"]


def test_snapshot_content_key_ignores_pr_impact():
    snap = build.load_snapshot(SNAP)
    assert build.content_key({**snap, "pr_impact": {"prs": [1]}}) == build.content_key(snap)
