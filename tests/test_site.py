import hashlib
import json
import os
import shutil

import pytest

from eipproof import build, chain, cli, health, sitecheck, smoke

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
    assert "cells: 15 not in [20, 40]" in errs
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
