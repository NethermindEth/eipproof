import json
import os
import subprocess

from eipproof import build, cli, config, diverge, render, smoke

SNAP = os.path.join(cli.ROOT, "snapshots", "2026-11-03.json")
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "divergence-bogota.json")

SPEC = """| Name                              | Value             |
|-----------------------------------|-------------------|
| `DEP_VERIFY_FRAME_MODE`           | `4`               |
| `LEANSPHINCS_SCHEME`              | `0x10`            |
| `AGGREGATED_VK`                   | `TBD`             |
| `AGGREGATION_INTERVAL`            | `1000` (milliseconds) |
"""

CS = """public static class Eip8288Constants
{
    public const byte DepVerifyFrameMode = 4;
    public const ulong LeanSphincsVerificationGas = 3_000;
}
"""

RS = """pub enum FrameMode {
    DepVerify = 3,
}
impl FrameMode {
    fn byte(&self) -> u8 {
        match self {
            FrameMode::DepVerify => 3,
        }
    }
}
pub const DEPENDENCY_SCHEME_LEANSPHINCS: u8 = 0x10;
const _: () = assert!(DEPENDENCY_SCHEME_LEANSPHINCS == 0x10);
"""


def test_spec_table_reads_values_units_and_tbd():
    t = diverge.spec_table(SPEC)
    assert t["DEP_VERIFY_FRAME_MODE"] == "4"
    assert t["LEANSPHINCS_SCHEME"] == "0x10"
    assert t["AGGREGATION_INTERVAL"] == "1000"
    assert t["AGGREGATED_VK"] == "TBD"
    assert diverge.number("TBD") is None
    assert diverge.number("0x10") == 16
    assert diverge.number("3_000") == 3000


def test_locate_finds_definitions_in_csharp_and_rust_only():
    assert diverge.locate(CS, "DepVerifyFrameMode") == [(3, "4")]
    assert diverge.locate(CS, "LeanSphincsVerificationGas") == [(4, "3_000")]
    assert diverge.locate(RS, "DepVerify") == [(2, "3")]
    assert diverge.locate(RS, "DEPENDENCY_SCHEME_LEANSPHINCS") == [(11, "0x10")]
    assert diverge.locate(RS, "Missing") == []


def obs(value, state="found", line=3):
    return {"value": value, "raw": str(value), "path": "a.rs", "line": line, "state": state}


def test_compare_marks_only_located_values_that_differ_from_the_spec():
    assert diverge.judge(4, obs(4)) == "match"
    assert diverge.judge(4, obs(3)) == "differs"
    assert diverge.judge(4, {"state": "not-located"}) == "not-located"
    assert diverge.judge(None, obs(3)) == "spec-tbd"
    assert diverge.judge(4, {"state": "unparsed", "raw": "A * B"}) == "unparsed"


def test_divergence_is_confirmed_only_by_a_failing_run_of_that_same_commit(tmp_path):
    block = json.load(open(FIXTURE))
    snap = build.load_snapshot(SNAP)
    snap["divergence"] = block
    rows = diverge.doc(snap)["divergences"]
    assert rows and all(r["status"] == "suspect" for r in rows)
    eip, client, sha = rows[0]["eip"], rows[0]["client"], rows[0]["sha"]
    run = snap["runs"].setdefault(client, {"eips": {}})
    run["eips"][eip] = {"failed": ["t"], "passed": 0, "total": 1}
    run["commit"] = "0" * 8
    assert all(r["status"] == "suspect" for r in diverge.doc(snap)["divergences"])
    run["commit"] = sha[:8]
    status = {r["sha"]: r["status"] for r in diverge.doc(snap)["divergences"]}
    assert status[sha] == "confirmed" and list(status.values()).count("confirmed") == 1


def test_a_failed_file_read_is_unreachable_and_only_a_404_is_missing(monkeypatch):
    def gh(stderr):
        def raw(path):
            raise subprocess.CalledProcessError(1, "gh", stderr=stderr)
        return raw
    monkeypatch.setattr(diverge.sources, "gh_raw", gh("gh: Not Found (HTTP 404)"))
    assert diverge.fetch_file("o/r", "a" * 40, "x.rs") is None
    monkeypatch.setattr(diverge.sources, "gh_raw", gh("gh: Bad Gateway (HTTP 502)"))
    monkeypatch.setattr(diverge, "spec_history", lambda repo, eip: ("EIPS/eip-8288.md", [("c" * 40, "2026-10-14T00:00:00Z", diverge.spec_table(SPEC))]))
    block = diverge.collect(None, log=lambda *_: None, fetch_ref=lambda repo, ref: ("a" * 40, "2026-11-01T00:00:00Z"))
    states = {o["state"] for r in block["eips"][0]["refs"] for o in r["obs"].values()}
    assert states == {"unreachable"}


def test_moving_branch_heads_alone_do_not_make_new_history():
    block = json.load(open(FIXTURE))
    moved = json.loads(json.dumps(block))
    for r in moved["eips"][0]["refs"]:
        r["sha"], r["date"] = "f" * 40, "2026-12-01T00:00:00Z"
    assert diverge.content(block) == diverge.content(moved)
    moved["eips"][0]["refs"][0]["obs"]["DEP_VERIFY_FRAME_MODE"]["value"] = 5
    assert diverge.content(block) != diverge.content(moved)


def test_pilot_8288_compares_nethermind_and_ethrex_and_finds_the_stale_branch():
    snap = build.load_snapshot(SNAP)
    snap["divergence"] = json.load(open(FIXTURE))
    d = diverge.doc(snap)
    assert diverge.check_doc(d) == []
    pilot = next(e for e in d["eips"] if e["eip"] == "8288")
    clients = {r["client"] for r in pilot["refs"]}
    assert {"nethermind", "ethrex"} <= clients
    current = [r for r in pilot["refs"] if r["ref"] in ("feature/eip8288-lean", "eip-8288-daisugi")]
    assert len(current) == 2
    assert all(r["counts"]["differs"] == 0 and r["counts"]["match"] >= 10 for r in current)
    stale = [x for x in d["divergences"] if x["ref"] == "eip-8288"]
    assert [(x["name"], x["spec"], x["value"]) for x in stale] == [("DEP_VERIFY_FRAME_MODE", 4, 3)]
    assert stale[0]["predates_spec"] is True
    assert stale[0]["url"].startswith(f'{config.GITHUB}/lambdaclass/ethrex/blob/{stale[0]["sha"]}/')
    assert stale[0]["url"].endswith(f'#L{stale[0]["line"]}')


def test_divergences_page_names_suspects_without_calling_them_bugs(tmp_path):
    snap = build.load_snapshot(SNAP)
    snap["divergence"] = json.load(open(FIXTURE))
    snap["source"] = "live"
    cli.write_site(snap, str(tmp_path))
    page = (tmp_path / "divergences.html").read_text()
    assert "EIP-8288" in page and "suspect" in page and "eip-8288-daisugi" in page
    assert "bug" not in page.lower()
    assert 'href="divergences.html"' in (tmp_path / "index.html").read_text()
    assert diverge.check_doc(json.loads((tmp_path / "api" / "divergences.json").read_text())) == []


def test_golden_8288_divergences(tmp_path):
    snap = build.load_snapshot(SNAP)
    snap["divergence"] = json.load(open(FIXTURE))
    snap["source"] = "live"
    cli.write_site(snap, str(tmp_path))
    got = json.loads((tmp_path / "api" / "divergences.json").read_text())
    golden = os.path.join(os.path.dirname(__file__), "fixtures", "divergences-8288.golden.json")
    if os.environ.get("UPDATE_GOLDEN"):
        json.dump(got, open(golden, "w"), indent=1, sort_keys=True)
    assert got == json.load(open(golden))


def test_site_without_comparisons_says_so(tmp_path):
    snap = build.load_snapshot(SNAP)
    snap["source"] = "live"
    cli.write_site(snap, str(tmp_path))
    assert "no cross-client comparison in this snapshot" in (tmp_path / "divergences.html").read_text()
    assert json.loads((tmp_path / "api" / "divergences.json").read_text())["eips"] == []


def test_check_doc_rejects_a_bad_status_and_a_missing_link():
    snap = build.load_snapshot(SNAP)
    snap["divergence"] = json.load(open(FIXTURE))
    d = diverge.doc(snap)
    d["divergences"][0]["status"] = "bug"
    del d["divergences"][0]["url"]
    errs = diverge.check_doc(d)
    assert any("status" in e for e in errs) and any("url" in e for e in errs)


def test_smoke_requires_the_divergence_page_and_json(tmp_path):
    assert "divergences.html" in smoke.PAGES
    snap = build.load_snapshot(SNAP)
    snap["divergence"] = json.load(open(FIXTURE))
    snap["source"] = "live"
    cli.write_site(snap, str(tmp_path))
    bad = json.loads((tmp_path / "api" / "divergences.json").read_text())
    bad["divergences"][0]["status"] = "bug"
    (tmp_path / "api" / "divergences.json").write_text(json.dumps(bad))
    assert smoke.check_divergences(lambda p: (tmp_path / "missing" / p).read_text())[0].startswith("api/divergences.json:")
    errs = smoke.check_divergences(lambda p: (tmp_path / p).read_text())
    assert any(e.startswith("divergences.json: row 0 status") for e in errs)
