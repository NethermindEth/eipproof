import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from datetime import datetime

import pytest

from eipproof import build, chain, cli, health, render, sitecheck, smoke

SNAP = os.path.join(cli.ROOT, "snapshots", "2026-11-03.json")
GOLDEN = os.path.join(os.path.dirname(__file__), "golden")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def rendered(tmp_path, source):
    snap = build.load_snapshot(SNAP)
    snap["source"] = source
    cells, _ = cli.write_site(snap, str(tmp_path))
    status = health.status_doc(snap, len(cells), 0, "c0ffee")
    (tmp_path / "api" / "status.json").write_text(json.dumps(status))
    return tmp_path


def site_files(root):
    out = {}
    for dirpath, _, files in os.walk(root):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            if rel != os.path.join("api", "status.json"):
                out[rel] = open(os.path.join(dirpath, name), "rb").read()
    return out


@pytest.fixture(scope="module")
def live_site(tmp_path_factory):
    return rendered(tmp_path_factory.mktemp("live"), "live")


@pytest.fixture(scope="module")
def fallback_site(tmp_path_factory):
    return rendered(tmp_path_factory.mktemp("fallback"), "snapshot")


def local_get(root):
    return lambda path: (root / path).read_text()


def test_golden_site(live_site):
    files = site_files(live_site)
    html = {k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items()) if k.endswith(".html")}
    data = {k: v for k, v in files.items() if not k.endswith(".html")}
    if UPDATE:
        shutil.rmtree(GOLDEN, ignore_errors=True)
        for k, v in data.items():
            os.makedirs(os.path.dirname(os.path.join(GOLDEN, k)), exist_ok=True)
            open(os.path.join(GOLDEN, k), "wb").write(v)
        json.dump(html, open(os.path.join(GOLDEN, "html.sha256.json"), "w"), indent=1, sort_keys=True)
    want_html = json.load(open(os.path.join(GOLDEN, "html.sha256.json")))
    assert html == want_html, "rendered HTML changed; rerun with UPDATE_GOLDEN=1 if intended"
    want = {k: open(os.path.join(GOLDEN, k), "rb").read() for k in data if os.path.exists(os.path.join(GOLDEN, k))}
    assert sorted(data) == sorted(set(site_files(GOLDEN)) - {"html.sha256.json"})
    for k in sorted(data):
        assert data[k] == want[k], k


def test_rendering_is_deterministic(live_site, tmp_path):
    assert site_files(rendered(tmp_path, "live")) == site_files(live_site)


def test_site_html_is_balanced_and_links_resolve(live_site, fallback_site):
    assert sitecheck.check_dir(str(live_site)) == []
    assert sitecheck.check_dir(str(fallback_site)) == []


def test_sitecheck_catches_broken_markup_and_links(tmp_path):
    (tmp_path / "a.html").write_text('<!doctype html><html><body><div><a href="missing.html">x</a></span></body></html>')
    errs = sitecheck.check_dir(str(tmp_path))
    assert any("broken link missing.html" in e for e in errs)
    assert any("</span> closes <div>" in e for e in errs)


def test_live_site_has_no_fallback_banner(live_site):
    assert 'id="fallback"' not in (live_site / "index.html").read_text()
    assert json.loads((live_site / "api" / "eip" / "7906.json").read_text())["source"] == "live"


def test_fallback_site_shows_snapshot_banner_on_every_page(fallback_site):
    for page in sorted(fallback_site.glob("*.html")):
        assert "data from snapshot 2026-11-03" in page.read_text(), page.name
    assert json.loads((fallback_site / "api" / "client" / "nethermind.json").read_text())["source"] == "snapshot"


def test_smoke_passes_on_built_site(live_site, fallback_site):
    assert smoke.check(local_get(live_site), "c0ffee") == []
    assert smoke.check(local_get(fallback_site), "c0ffee") == []


def test_smoke_rejects_old_deploy(live_site):
    assert smoke.check(local_get(live_site), "deadbeef") == ["api/status.json: commit 'c0ffee', want 'deadbeef'"]


def test_smoke_rejects_missing_banner_and_bad_schema(tmp_path, live_site):
    site = tmp_path / "s"
    shutil.copytree(live_site, site)
    status = json.loads((site / "api" / "status.json").read_text())
    (site / "api" / "status.json").write_text(json.dumps({**status, "source": "snapshot"}))
    doc = json.loads((site / "api" / "eip" / "7906.json").read_text())
    doc["cells"] = [c for c in doc["cells"] if c["client"] != "nethermind"]
    del doc["fork"]
    (site / "api" / "eip" / "7906.json").write_text(json.dumps(doc))
    errs = smoke.check(local_get(site))
    assert "index.html: fallback banner missing for source 'snapshot'" in errs
    assert "api/eip/7906.json: missing ['fork']" in errs
    assert "api/eip/7906.json: no 7906 x nethermind cell" in errs


def test_smoke_rejects_cell_count_out_of_range(tmp_path, live_site):
    site = tmp_path / "s"
    shutil.copytree(live_site, site)
    for path in (site / "api" / "client").glob("*.json"):
        doc = json.loads(path.read_text())
        path.write_text(json.dumps({**doc, "cells": doc["cells"][:3]}))
    errs = smoke.check(local_get(site))
    assert "cells: 15 not in [20, 200]" in errs
    assert "cells: status says 40, client JSON has 15" in errs


def test_live_failures_count_in_a_row():
    assert health.live_failures(None, True) == 1
    assert health.live_failures({"live_failures": 2}, True) == 3
    assert health.live_failures({"live_failures": 2}, False) == 0
    assert health.fetch_status("http://127.0.0.1:9/status.json") is None


def test_editorial_delta_does_not_open_the_cell():
    snap = {"eips": {"7906": {"head": "h" * 40, "pin": {"blob": "b" * 40, "commit": "p" * 40, "ambiguous": False},
                              "deltas": [{"commit": "9099f412" + "0" * 32, "candidates": []}], "pending": []}},
            "runs": {"nethermind": {"release": "tests-bogota-devnet@v2.0.0", "image": "i", "version": "v", "url": "u",
                                    "eips": {"7906": {"total": 3, "passed": 3, "failed": []}}, "results": {}}},
            "newest_release": "tests-bogota-devnet@v2.0.0"}
    proof = [{"eip": "7906", "commit": "9099f412", "kind": "editorial", "reason": "typo", "killed": []}]
    cell = chain.chain("7906", "nethermind", snap, proof)
    assert cell["links"]["test"]["deltas"][0]["state"] == "editorial"
    assert cell["headline"] == "pass"
    assert chain.queue([cell], ["7906"]) == []


def markdown_in(text, start=""):
    return html.unescape(re.search(re.escape(start) + r'.*?<textarea class="md"[^>]*>(.*?)</textarea>', text, re.S).group(1))


def test_cell_copies_as_markdown_with_why_and_sources(live_site):
    doc = json.loads((live_site / "api" / "eip" / "8141.json").read_text())
    cell = next(c for c in doc["cells"] if c["client"] == "nethermind")
    text = markdown_in((live_site / "index.html").read_text(), '<template id="t-8141-nethermind">')
    assert text.startswith(f"**EIP-8141 x Nethermind: {cell['text']}**")
    assert cell["why"] in text
    assert cell["links"]["run"]["url"] in text
    assert "dc5d5fa6](https://github.com/ethereum/EIPs/commit/dc5d5fa6" in text and ": proven (" in text
    assert "proofs/8141-dc5d5fa6.patch" in text
    assert "https://nethermindeth.github.io/eipproof/index.html#8141-nethermind" in text


def test_every_cell_drawer_has_a_copy_button(live_site):
    page = (live_site / "index.html").read_text()
    assert page.count('onclick="copyMd(this)"') == page.count("<template id=") == 40


def test_eip_page_copies_as_markdown_with_every_client_and_change(live_site):
    text = markdown_in((live_site / "eip-7906.html").read_text())
    for label in ("Nethermind", "Geth", "Reth", "ethrex", "Besu"):
        assert f"\n- {label}: " in text
    assert "9099f412d228ec80ec27b713df6da61993bf4702) 2026-10-27" in text and "nonce changes appear: proven" in text
    assert "https://nethermindeth.github.io/eipproof/eip-7906.html" in text


def test_feed_lists_every_spec_change_newest_first_with_state(live_site):
    snap = build.load_snapshot(SNAP)
    doc = json.loads((live_site / "api" / "changes.json").read_text())
    rows = doc["changes"]
    assert len(rows) == sum(len(i["revisions"]) for i in snap["eips"].values())
    dates = [datetime.fromisoformat(r["date"]) for r in rows]
    assert dates == sorted(dates, reverse=True)
    by = {(r["eip"], r["commit"][:8]): r["word"] for r in rows}
    assert by[("8141", "dc5d5fa6")] == "proven"
    assert by[("7906", "9099f412")] == "proven"
    assert by[("7906", "25ac2920")] == "EELS v2.0.0 implements this text"
    page = (live_site / "changes.html").read_text()
    assert page.count('<div class="rev" data-eip=') == len(rows)
    assert '<select id="f" onchange="filt(this.value)">' in page
    for eip in snap["eips"]:
        n = sum(r["eip"] == eip for r in rows)
        assert f'<option value="{eip}">EIP-{eip} ({n})</option>' in page
        assert page.count(f'data-eip="{eip}"') == n


def test_feed_marks_unproven_and_editorial_changes():
    snap = build.load_snapshot(SNAP)
    info = snap["eips"]["8141"]
    commit = info["deltas"][0]["commit"]
    assert render.rev_state("8141", info, {"commit": commit}, [])[1] == "untested"
    editorial = [{"eip": "8141", "commit": commit[:8], "kind": "editorial", "reason": "typo"}]
    assert render.rev_state("8141", info, {"commit": commit}, editorial)[1] == "wording only"


def test_every_page_links_the_feed_and_carries_the_snapshot_age_hook(live_site, fallback_site):
    hook = f'<div class="strip age" id="stale" role="status" hidden data-taken="{build.load_snapshot(SNAP)["taken_at"]}"></div>'
    for site in (live_site, fallback_site):
        for page in sorted(site.glob("*.html")):
            text = page.read_text()
            assert '<a href="changes.html"' in text, page.name
            assert hook in text, page.name


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_stale_banner_shows_only_after_six_hours():
    taken = "2026-11-03T21:21:33Z"
    script = ("globalThis.addEventListener=()=>{};" + render.JS +
              ";const t=Date.parse('%s');console.log(JSON.stringify([5.9,6.1,30].map(h=>staleText('%s',t+h*36e5))))" % (taken, taken))
    out = json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout)
    assert out[0] == ""
    assert out[1] == "data from snapshot 2026-11-03 21:21 UTC, 6 h old: newer runs or spec changes may exist"
    assert out[2].startswith("data from snapshot 2026-11-03 21:21 UTC, 30 h old")


def test_smoke_rejects_missing_feed(tmp_path, live_site):
    site = tmp_path / "s"
    shutil.copytree(live_site, site)
    (site / "changes.html").unlink()
    (site / "api" / "changes.json").write_text(json.dumps({"changes": []}))
    errs = smoke.check(local_get(site))
    assert any(e.startswith("changes.html: ") for e in errs)
    assert "api/changes.json: no changes" in errs



def untested_info(eip, stage, category, title):
    rev = {"commit": eip.ljust(40, "a"), "date": "2026-10-20T10:00:00+00:00", "subject": f"Update EIP-{eip}", "blob": "c" * 40}
    return {"eip": eip, "path": f"EIPS/eip-{eip}.md", "test_dir": None, "checked": f"tests/bogota/eip{eip}_*",
            "head": rev["commit"], "head_blob": rev["blob"], "head_date": rev["date"], "revisions": [rev], "pin": None,
            "deltas": [], "pending": [], "title": title, "status": "Draft", "category": category, "stage": [stage]}


@pytest.fixture(scope="module")
def wide_site(tmp_path_factory):
    snap = build.load_snapshot(SNAP)
    snap["source"] = "live"
    snap["eips"]["7805"] = untested_info("7805", "Scheduled", "Core", "Fork-choice enforced Inclusion Lists")
    snap["eips"]["8077"] = untested_info("8077", "Considered", "Networking", "Announce nonce")
    root = tmp_path_factory.mktemp("wide")
    cells, _ = cli.write_site(snap, str(root))
    (root / "api" / "status.json").write_text(json.dumps(health.status_doc(snap, len(cells), 0, "c0ffee")))
    return root, cells


def test_untested_sfi_cfi_eips_get_rows_but_no_cells(wide_site):
    root, cells = wide_site
    assert {c["eip"] for c in cells} == {"8141", "7906", "8250", "8151", "8272", "8298", "4758", "8253"}
    page = (root / "index.html").read_text()
    order = [m for m in re.findall(r'<th class="row"><a href="eip-(\d+)\.html"', page)]
    assert order == ["8141", "7805", "7906", "8250", "8151", "8272", "8298", "4758", "8253", "8077"]
    row = re.search(r'<tr class="nt" id="r-7805">.*?</tr>', page).group(0)
    assert "no tests yet" in row and "checked tests/bogota/eip7805_*" in row and "v2.0.0" in row
    assert 'class="c none"' in row and " ok" not in row
    assert '<span class="pill sb">SFI</span>' in row


def test_coverage_line_counts_sfi_cfi_and_names_networking(wide_site):
    root, _ = wide_site
    page = (root / "index.html").read_text()
    assert "SFI+CFI in Hegotá: 10 EIPs, 8 with EELS tests, 2 without" in page
    assert "Networking EIPs (EIP-8077) are out of EELS scope" in page


def test_eips_json_lists_every_row(wide_site):
    root, _ = wide_site
    doc = json.loads((root / "api" / "eips.json").read_text())
    by = {r["eip"]: r for r in doc["eips"]}
    assert len(by) == 10
    assert by["7805"]["test_dir"] is None and by["7805"]["checked"] == "tests/bogota/eip7805_*" and by["7805"]["behind"] is None
    assert by["7906"]["test_dir"].endswith("eip7906_transaction_assertions") and by["8077"]["category"] == "Networking"


def test_untested_eip_page_and_feed(wide_site):
    root, _ = wide_site
    page = (root / "eip-7805.html").read_text()
    assert "no tests yet" in page and "No client cell is shown" in page
    feed = json.loads((root / "api" / "changes.json").read_text())["changes"]
    assert any(r["eip"] == "7805" and r["word"] == "no EELS tests" for r in feed)
    assert sitecheck.check_dir(str(root)) == []
    assert smoke.check(local_get(root)) == []
