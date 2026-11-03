import glob
import json
import os

import pytest

from eipproof import build, cli, render
from eipproof.chain import headline_text

SNAPS = sorted(glob.glob(os.path.join(cli.ROOT, "snapshots", "*.json")))
pytestmark = pytest.mark.skipif(not SNAPS, reason="no live snapshot; run make build")


@pytest.fixture(scope="module")
def live():
    snap = build.load_snapshot(SNAPS[-1])
    cells = {(c["eip"], c["client"]): c for c in render.cells_for(snap, cli.load_proofs())}
    return snap, cells


def test_nethermind_7906_passes_on_devnet_image(live):
    snap, cells = live
    cell = cells[("7906", "nethermind")]
    run = cell["links"]["run"]
    assert (run["passed"], run["total"]) == (184, 184)
    assert headline_text(cell) == "pass 184/184"
    assert run["release"] == snap["newest_release"] == "tests-bogota-devnet@v2.0.0"
    assert "bogota-devnet" in run["image"]
    assert run["url"].startswith("https://hive.ethpandaops.io/bogota/suite.html?")


def test_besu_7906_is_stale_release(live):
    _, cells = live
    run = cells[("7906", "besu")]["links"]["run"]
    assert cells[("7906", "besu")]["headline"] == "stale-release"
    assert (run["passed"], run["total"], run["release"]) == (299, 305, "tests-bogota-devnet@v1.1.1")


def test_7906_pin_lag_covered_by_mutant_kill(live):
    _, cells = live
    deltas = cells[("7906", "nethermind")]["links"]["test"]["deltas"]
    assert [d["commit"][:8] for d in deltas] == ["9099f412"]
    assert deltas[0]["state"] == "covered"
    assert deltas[0]["attestation"]["killed"] == [
        "tests/bogota/eip7906_transaction_assertions/test_txtrace.py::test_sender_nonce_change"
        "[fork_Bogota-blockchain_test_engine_from_state_test-keyed_nonce]"]


def test_8141_nonce_bound_covered_by_mutant_kill(live):
    _, cells = live
    deltas = cells[("8141", "nethermind")]["links"]["test"]["deltas"]
    assert [(d["commit"][:8], d["state"]) for d in deltas] == [("dc5d5fa6", "covered")]
    assert deltas[0]["cases"] == 1


def test_open_spec_pr_is_overlay_only(live):
    snap, cells = live
    pending = {p["number"]: p for p in snap["eips"]["7906"]["pending"]}
    assert pending[12304]["merged"] is False
    spec = cells[("7906", "nethermind")]["links"]["spec"]
    assert spec["behind"] == 1
    assert all(d["commit"][:8] == "9099f412" for d in snap["eips"]["7906"]["deltas"])


def test_site_writes_eip_and_client_pages_with_json(live, tmp_path):
    snap, _ = live
    render.site(snap, cli.load_proofs(), str(tmp_path))
    for eip in snap["eips"]:
        assert (tmp_path / f"eip-{eip}.html").exists()
    page = (tmp_path / "eip-7906.html").read_text()
    assert "9099f412" in page and "client-nethermind.html" in page
    doc = json.loads((tmp_path / "api" / "client" / "besu.json").read_text())
    assert {c["eip"] for c in doc["cells"]} == set(snap["eips"])
    assert all(c["client"] == "besu" for c in doc["cells"])
    assert doc["newest_release"] == snap["newest_release"]
    besu = (tmp_path / "client-besu.html").read_text()
    assert "newest is v2.0.0" in besu


def test_matrix_counts_match_cells(live):
    _, cells = live
    nm = [c for c in cells.values() if c["client"] == "nethermind"]
    assert sum(n for _, n in render.headline_counts(nm)) == len(nm)
