import json
import os
import re
import subprocess

import pytest

from eipproof import build, cli, config, handoff, render

SNAP = os.path.join(cli.ROOT, "snapshots", "2026-11-03.json")


def item(number, title, state="open", merged_at=None):
    return {"number": number, "title": title, "html_url": f"https://github.com/x/y/pull/{number}", "state": state, "draft": False,
            "created_at": "2026-10-01T00:00:00Z", "pull_request": {"merged_at": merged_at}}


def fake_search(pages):
    calls = []

    def fake(path):
        calls.append(path)
        repo = re.search(r"repo:([^+]+)", path).group(1)
        rows = pages.get(repo)
        if isinstance(rows, Exception):
            raise rows
        rows = rows or []
        return {"total_count": len(rows), "items": rows}

    return fake, calls


def test_title_mention_needs_the_eip_word_and_exact_number():
    assert handoff.title_mentions("feat: implement EIP-7906 assertions", "7906")
    assert handoff.title_mentions("eip7906: opcodes", "7906")
    assert handoff.title_mentions("Bogota: EIP 7906 and EIP-8141", "8141")
    assert not handoff.title_mentions("EIP-79060 thing", "7906")
    assert not handoff.title_mentions("fix #7906 crash", "7906")
    assert not handoff.title_mentions("seip7906", "7906")


def test_collect_keeps_open_and_merged_client_prs_and_open_eels_prs(monkeypatch):
    fake, calls = fake_search({
        config.CLIENT_REPO["nethermind"]: [item(3, "EIP-7906 opcodes"), item(2, "EIP-7906 old", "closed", "2026-10-02T00:00:00Z"),
                                           item(1, "EIP-7906 abandoned", "closed"), item(4, "fix #7906 crash")],
        config.EELS_REPO: [item(9, "feat(tests): EIP-8141 frames")],
    })
    monkeypatch.setattr(handoff.sources, "gh_api", fake)
    out = handoff.collect(["7906", "8141"], log=lambda *_: None, gap=0)
    nm = out["nethermind"]
    assert nm["state"] == "ok" and nm["repo"] == config.CLIENT_REPO["nethermind"]
    assert [(p["number"], p["state"]) for p in nm["eips"]["7906"]] == [(3, "open"), (2, "merged")]
    assert "8141" not in nm["eips"]
    assert [p["number"] for p in out["eels"]["eips"]["8141"]] == [9]
    assert all("is:open" in c for c in calls if config.EELS_REPO in c)
    assert set(out) == {"eels", *config.CLIENTS}


def test_collect_batches_numbers_under_the_search_operator_limit(monkeypatch):
    fake, calls = fake_search({})
    monkeypatch.setattr(handoff.sources, "gh_api", fake)
    eips = [str(7000 + i) for i in range(13)]
    handoff.collect(eips, log=lambda *_: None, gap=0)
    per_repo = [c for c in calls if config.CLIENT_REPO["reth"] in c]
    assert len(per_repo) == 5
    assert all(c.count("+OR+") <= 5 for c in calls)
    assert all(f"eip{e}" in "".join(per_repo) for e in eips)


def test_failed_lookup_is_unreachable_not_empty(monkeypatch):
    fake, _ = fake_search({config.CLIENT_REPO["besu"]: subprocess.CalledProcessError(1, "gh")})
    monkeypatch.setattr(handoff.sources, "gh_api", fake)
    monkeypatch.setattr(handoff.time, "sleep", lambda s: None)
    out = handoff.collect(["7906"], log=lambda *_: None, gap=0)
    assert out["besu"]["state"] == "unreachable" and out["besu"]["eips"] == {}
    assert out["reth"]["state"] == "ok"


def test_truncated_search_is_flagged(monkeypatch):
    def fake(path):
        return {"total_count": 1000, "items": [item(i, "EIP-7906 x") for i in range(100)]}

    monkeypatch.setattr(handoff.sources, "gh_api", fake)
    out = handoff.collect(["7906"], log=lambda *_: None, gap=0)
    assert out["geth" if "geth" in out else "go-ethereum"]["truncated"] is True


LINKED = {
    "eels": {"repo": config.EELS_REPO, "state": "ok", "truncated": False,
             "eips": {"7906": [{"number": 3999, "title": "feat(tests): EIP-7906 nonce changes", "url": "https://github.com/ethereum/execution-specs/pull/3999",
                                "state": "open", "draft": False, "created": "2026-11-01", "merged": None}]}},
    "nethermind": {"repo": config.CLIENT_REPO["nethermind"], "state": "ok", "truncated": False,
                   "eips": {"7906": [{"number": 14374, "title": "EIP-7906 refactor", "url": "https://github.com/NethermindEth/nethermind/pull/14374",
                                      "state": "merged", "draft": False, "created": "2026-10-20", "merged": "2026-10-27T00:00:00Z"}]}},
    "besu": {"repo": config.CLIENT_REPO["besu"], "state": "unreachable", "reason": "CalledProcessError", "eips": {}},
}


def snap_with(linked):
    snap = build.load_snapshot(SNAP)
    snap["source"] = "live"
    if linked is not None:
        snap["linked_prs"] = linked
    return snap


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("handoff")
    cells, _ = cli.write_site(snap_with(LINKED), str(out))
    return out, cells


def test_pending_prs_never_change_a_verdict():
    base = {(c["eip"], c["client"]): c["headline"] for c in render.cells_for(snap_with(None), cli.load_proofs())}
    linked = {(c["eip"], c["client"]): c["headline"] for c in render.cells_for(snap_with(LINKED), cli.load_proofs())}
    assert base == linked


def test_brief_json_exists_for_every_non_pass_cell_only(site):
    out, cells = site
    briefs = {p[:-5] for p in os.listdir(out / "api" / "brief")}
    assert briefs == {f'{c["eip"]}-{c["client"]}' for c in cells if c["headline"] != "pass"}
    assert briefs


def test_brief_carries_spec_diff_tests_and_client_prs(site):
    out, cells = site
    cell = next(c for c in cells if c["eip"] == "7906" and c["headline"] != "pass" and c["client"] == "besu")
    doc = json.loads((out / "api" / "brief" / "7906-besu.json").read_text())
    assert doc["eip"] == "7906" and doc["client"] == "besu" and doc["headline"] == cell["headline"]
    assert any(ch["url"].startswith("https://github.com/ethereum/EIPs/commit/9099f412") for ch in doc["spec"]["changes"])
    assert doc["tests"]["failed"] == cell["links"]["run"]["failed"]
    assert doc["client_prs"]["state"] == "unreachable"
    assert any(p["repo"] == config.EIPS_REPO and p["number"] == 12304 for p in doc["pending_spec"])
    assert any(p["repo"] == config.EELS_REPO and p["number"] == 3999 for p in doc["pending_spec"])
    assert doc["hints"]["state"] == "none"
    md = handoff.brief_markdown(doc)
    assert "EIP-7906" in md and "Besu" in md and "lookup failed" in md and "execution-specs/pull/3999" in md


def test_brief_never_links_to_an_action_that_opens_something(site):
    out, _ = site
    for name in os.listdir(out / "api" / "brief"):
        text = (out / "api" / "brief" / name).read_text()
        assert "/compare/" not in text and "/pull/new" not in text and "/issues/new" not in text


def test_drawer_has_brief_button_only_for_non_pass_cells(site):
    out, cells = site
    page = (out / "index.html").read_text()
    assert page.count("Copy implement brief") == sum(c["headline"] != "pass" for c in cells)
    assert page.count(">Copy as Markdown<") == len(cells)


def test_eip_page_lists_pending_spec_prs_and_client_prs_per_client(site):
    out, _ = site
    page = (out / "eip-7906.html").read_text()
    assert "EIPs#12304" in page
    assert "execution-specs/pull/3999" in page
    assert "nethermind/pull/14374" in page and "merged" in page
    assert re.search(r"Besu</[^>]+>.*?lookup failed", page, re.S)
    assert re.search(r"Geth</[^>]+>.*?not collected", page, re.S)


def test_old_snapshot_without_linked_prs_says_not_collected(tmp_path):
    cli.write_site(snap_with(None), str(tmp_path))
    page = (tmp_path / "eip-7906.html").read_text()
    assert "not collected in this snapshot" in page


def test_feed_shows_open_spec_prs_as_not_counted(site):
    out, _ = site
    page = (out / "changes.html").read_text()
    assert "EIPs#12304" in page and "execution-specs/pull/3999" in page and "not counted" in page
    doc = json.loads((out / "api" / "changes.json").read_text())
    assert all(r["commit"] for r in doc["changes"])
    assert any(p["number"] == 12304 for p in doc["pending"])
