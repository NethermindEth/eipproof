import json
import os

import pytest
import yaml

from eipproof import cli, traffic


def api(views, clones, referrers=(), paths=()):
    def row(day, n, u):
        return {"timestamp": f"{day}T00:00:00Z", "count": n, "uniques": u}
    data = {
        "repos/o/r/traffic/views": {"count": sum(v[1] for v in views), "uniques": 3, "views": [row(*v) for v in views]},
        "repos/o/r/traffic/clones": {"count": sum(c[1] for c in clones), "uniques": 2, "clones": [row(*c) for c in clones]},
        "repos/o/r/traffic/popular/referrers": list(referrers),
        "repos/o/r/traffic/popular/paths": list(paths),
    }
    return data.__getitem__


def read(root, name):
    return json.loads((root / "traffic" / name).read_text())


def test_records_finished_days_and_keeps_days_older_than_the_api_window(tmp_path):
    traffic.record("o/r", str(tmp_path), api([("2026-11-03", 4, 2), ("2026-11-05", 9, 9)], [("2026-11-04", 7, 1)]), "2026-11-05")
    assert [d["date"] for d in read(tmp_path, "daily.json")] == ["2026-11-03", "2026-11-04"]
    traffic.record("o/r", str(tmp_path), api([("2026-11-05", 5, 1), ("2026-11-06", 1, 1)], []), "2026-11-06")
    days = {d["date"]: d for d in read(tmp_path, "daily.json")}
    assert sorted(days) == ["2026-11-03", "2026-11-04", "2026-11-05"]
    assert days["2026-11-03"]["views"] == {"count": 4, "uniques": 2}
    assert days["2026-11-04"]["clones"] == {"count": 7, "uniques": 1} and days["2026-11-04"]["views"] == {"count": 0, "uniques": 0}
    assert days["2026-11-05"]["views"] == {"count": 5, "uniques": 1}


def test_badge_takes_totals_from_the_api_and_carries_the_date(tmp_path):
    traffic.record("o/r", str(tmp_path), api([("2026-11-04", 4, 2)], [("2026-11-04", 7, 1)]), "2026-11-05")
    badge = read(tmp_path, "badge.json")
    assert badge["schemaVersion"] == 1 and badge["label"] == "GitHub repo, 14d"
    assert badge["message"] == "4 views, 3 unique, 7 clones, 2026-11-05"


def test_latest_counts_visits_that_came_from_the_site(tmp_path):
    refs = [{"referrer": "nethermindeth.github.io", "count": 6, "uniques": 2}, {"referrer": "github.com", "count": 3, "uniques": 1}]
    traffic.record("o/r", str(tmp_path), api([], [], refs), "2026-11-05")
    latest = read(tmp_path, "latest.json")
    assert latest["from_site"] == {"count": 6, "uniques": 2} and latest["referrers"] == refs
    assert "fetched_at" not in latest


def test_same_numbers_on_the_same_day_change_no_file(tmp_path):
    get = api([("2026-11-04", 4, 2)], [])
    traffic.record("o/r", str(tmp_path), get, "2026-11-05")
    before = {p.name: p.read_bytes() for p in (tmp_path / "traffic").iterdir()}
    traffic.record("o/r", str(tmp_path), get, "2026-11-05")
    assert {p.name: p.read_bytes() for p in (tmp_path / "traffic").iterdir()} == before


@pytest.mark.parametrize("date,warn", [(None, "no traffic/badge.json"), ("2026-11-02", "3 days old"), ("2026-11-04", "")])
def test_check_warns_when_the_recorder_stopped(tmp_path, date, warn):
    if date:
        traffic.record("o/r", str(tmp_path), api([], []), date)
    out = traffic.check(str(tmp_path), "2026-11-05")
    assert (warn in out) if warn else out == ""


def test_pages_workflow_warns_on_stale_traffic_and_retries_the_data_push():
    jobs = yaml.safe_load(open(os.path.join(cli.ROOT, ".github", "workflows", "pages.yml")))["jobs"]
    runs = {name: "\n".join(s.get("run", "") for s in job["steps"]) for name, job in jobs.items()}
    assert any("python3 -m eipproof.traffic check data" in r for r in runs.values())
    archive = next(r for r in runs.values() if "commit -qm \"snapshots from" in r)
    assert "for i in 1 2 3" in archive and 'cherry-pick "$c"' in archive
