import copy
import json
import os
import shutil

from eipproof import cli, digest

API = os.path.join(os.path.dirname(__file__), "golden", "api")
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def golden(name, text):
    path = os.path.join(FIXTURES, name)
    if UPDATE:
        with open(path, "w") as f:
            f.write(text)
    assert text == open(path).read()


def week_before(state):
    prev = copy.deepcopy(state)
    prev["snapshot"] = "2026-10-27T09:00:00Z"
    prev["newest_release"] = "tests-bogota-devnet@v1.1.1"
    prev["stages"]["8141"] = "Considered"
    prev["stages"]["9999"] = "Considered"
    del prev["stages"]["4758"]
    prev["cells"]["reth"]["8253"] = "pass"
    prev["cells"]["besu"]["8141"] = "pass"
    prev["behind"] = {"7906": prev["behind"]["7906"], "8298": "0123456789abcdef"}
    prev["pending"] = prev["pending"][2:] + ["ethereum/EIPs#1", "ethereum/EIPs#2", "ethereum/EIPs#3"]
    return prev


def test_digest_text_matches_golden():
    golden("digest.golden.txt", digest.render(digest.load(API)))


def test_week_over_week_matches_golden():
    api = digest.load(API)
    golden("digest-week.golden.txt", digest.render(api, week_before(digest.state(api))))


def test_same_input_gives_same_text_and_state():
    a, b = digest.load(API), digest.load(API)
    assert digest.render(a) == digest.render(b)
    assert json.dumps(digest.state(a), sort_keys=True) == json.dumps(digest.state(b), sort_keys=True)


def test_unchanged_week_says_so():
    api = digest.load(API)
    text = digest.render(api, digest.state(api))
    assert "*Since last week* (2026-11-03): no changes" in text


def test_reads_the_api_over_a_url():
    assert digest.render(digest.load("file://" + API)) == digest.render(digest.load(API))


def test_status_names_a_snapshot_fallback(tmp_path):
    api = tmp_path / "api"
    shutil.copytree(API, api)
    (api / "status.json").write_text(json.dumps({"source": "snapshot", "snapshot": "2026-11-03T23:25:54Z"}))
    assert "site shows the 2026-11-03 23:25 UTC snapshot, live data failed" in digest.render(digest.load(str(api)))


def test_slack_control_characters_are_escaped():
    assert digest.escape("a<b> & c") == "a&lt;b&gt; &amp; c"


def test_cli_prints_text_and_writes_state(tmp_path, capsys):
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps(week_before(digest.state(digest.load(API)))))
    out = tmp_path / "state.json"
    cli.main(["digest", "--api", API, "--prev", str(prev), "--state-out", str(out)])
    assert capsys.readouterr().out == open(os.path.join(FIXTURES, "digest-week.golden.txt")).read()
    assert json.loads(out.read_text()) == digest.state(digest.load(API))


def test_cli_ignores_a_missing_prev_file(tmp_path, capsys):
    cli.main(["digest", "--api", API, "--prev", str(tmp_path / "none.json")])
    assert capsys.readouterr().out == open(os.path.join(FIXTURES, "digest.golden.txt")).read()
