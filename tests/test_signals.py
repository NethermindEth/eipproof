import json
import os
import re

import pytest

from eipproof import build, cli, config, health

SNAP = os.path.join(cli.ROOT, "snapshots", "2026-11-03.json")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("signals")
    snap = build.load_snapshot(SNAP)
    snap["source"] = "live"
    cells, _ = cli.write_site(snap, str(root))
    (root / "api" / "status.json").write_text(json.dumps(health.status_doc(snap, len(cells), 0, "c0ffee")))
    return root, snap


def read(root, name):
    return (root / name).read_text()


def visible(text):
    return re.sub(r"<template\b.*?</template>", "", text, flags=re.S)


def template(text, tid):
    return re.search(rf'<template id="t-{tid}">(.*?)</template>', text, re.S).group(1)


def header(text):
    return text.split("</header>")[0]


def popover(text, cls):
    return re.search(rf'<details class="pop {cls}">(.*?)</details>', text, re.S).group(1)


def g1(root, snap):
    for name in ("index.html", "eip-8141.html", "client-reth.html", "queue.html"):
        top = header(read(root, name))
        assert '<nav class="forks" aria-label="Fork">' in top
        assert all(f'>{v["FORK_LABEL"]}</a>' in top for v in config.FORKS.values())


def g2(root, snap):
    for name in ("index.html", "eip-8141.html", "client-reth.html", "changes.html"):
        top = header(read(root, name))
        for href in ("start.html", "index.html", "queue.html", "changes.html"):
            assert f'<a href="{href}"' in visible(top).split('<details class="pop more">')[0], (name, href)
        more = popover(top, "more")
        for href in ("releases.html", "divergences.html", "prs.html", "history.html"):
            assert f'<a href="{href}"' in more, (name, href)


def g3(root, snap):
    for name in ("index.html", "eip-8141.html", "client-reth.html"):
        mine = popover(header(read(root, name)), "clients")
        for c in config.CLIENTS:
            assert f'<a href="client-{c}.html"' in mine and config.CLIENT_LABEL[c] in mine


def g4(root, snap):
    for name in ("index.html", "client-reth.html"):
        pop = popover(header(read(root, name)), "snap")
        assert snap["newest_release"] in pop and snap["taken_at"] in pop
        assert snap["listing_url"] in pop and f'{snap["listing_rows"]}</span> runs' in pop
        assert 'as of <a href="s/' in pop


def g5(root, snap):
    text = read(root, "index.html")
    assert f'data-taken="{snap["taken_at"]}"' in header(text) and 'id="age"' in header(text)
    assert 'id="stale"' in text
    assert 'id="fallback"' not in text


def test_offline_build_says_the_live_rebuild_did_not_run(tmp_path):
    snap = build.load_snapshot(SNAP)
    snap["source"] = "snapshot"
    cli.write_site(snap, str(tmp_path))
    for name in ("index.html", "eip-8141.html", "client-reth.html", "queue.html"):
        main = read(tmp_path, name).split("<main>")[1]
        assert main.startswith('<div class="strip" id="fallback" role="alert">'), name
        assert "the live rebuild did not run" in main, name


def g6(root, snap):
    assert '<a class="jsn" href="api/eips.json">JSON</a>' in visible(read(root, "index.html"))
    assert '<a class="jsn" href="api/eip/8141.json">JSON</a>' in visible(read(root, "eip-8141.html"))
    assert '<a class="jsn" href="api/client/reth.json">JSON</a>' in visible(read(root, "client-reth.html"))
    for name in ("queue.html", "changes.html", "releases.html", "divergences.html", "prs.html"):
        assert 'class="jsn"' in visible(read(root, name)), name


def m1(root, snap):
    text = visible(read(root, "index.html"))
    for c, run in snap["runs"].items():
        th = re.search(rf'<th class="ch" data-cl="{c}" scope="col">(.*?)</th>', text, re.S).group(1)
        assert f'href="client-{c}.html"' in th and run["release"].split("@")[-1] in th
    assert "old release" in re.search(r'<th class="ch" data-cl="besu" scope="col">(.*?)</th>', text, re.S).group(1)


def m2(root, snap):
    text = visible(read(root, "index.html"))
    sums = re.search(r'<tr class="sums">(.*?)</tr>', text, re.S).group(1)
    assert "by weakest check" in sums
    reth = re.search(r'<td class="sum" data-cl="reth" title="([^"]*)"', sums).group(1)
    assert reth == "1 fails · 7 pass"


def m3(root, snap):
    text = visible(read(root, "index.html"))
    row = re.search(r'<tr id="r-8141"[^>]*>(.*?)</tr>', text, re.S).group(1)
    assert 'href="eip-8141.html"' in row and "Frame Transaction" in row
    assert '<span class="pill sb">SFI</span>' in row and "Scheduled" in row and "Draft" in row


def m4(root, snap):
    row = re.search(r'<tr id="r-8141"[^>]*>(.*?)</tr>', visible(read(root, "index.html")), re.S).group(1)
    assert 'class="nb d"' in row and ">1</span>" in row.split('class="nb d"')[1]
    assert 'class="nb p"' in row and ">11</span>" in row.split('class="nb p"')[1]


def m5(root, snap):
    text = read(root, "index.html")
    cell = re.search(r'<td class="c bad" id="c-8253-reth"[^>]*>(.*?)</td>', visible(text), re.S).group(1)
    run = snap["runs"]["reth"]
    assert 'class="g"' in cell and re.search(r"\d+/\d+", cell)
    drawer = template(text, "8253-reth")
    assert 'class="dhl"' in drawer and 'title="devnet image tag"' in drawer
    assert 'class="next"' in drawer and "owner Reth" in drawer
    assert run["image"].rsplit(":", 1)[-1].replace("-linux-amd64", "") in drawer


def m6(root, snap):
    text = read(root, "index.html")
    drawer = template(text, "8141-nethermind")
    for name in ("Spec change", "Test proof", "Client run"):
        assert f'<span class="cname">{name}</span>' in drawer
    assert 'class="legend"' in visible(text) and "How to read" in visible(text)


def m7(root, snap):
    text = read(root, "index.html")
    eels = re.search(r'<td class="c eels [a-z]+" id="c-8141-eels"[^>]*>(.*?)</td>', visible(text), re.S).group(1)
    assert 'data-open="8141-eels"' in eels
    drawer = template(text, "8141-eels")
    assert "owner EELS" in drawer and "spec changes proven" in drawer and "dc5d5fa6" in drawer


def m8(root, snap):
    text = visible(read(root, "index.html"))
    line = re.search(r"Failing cases in untracked EIP tests, not counted:(.*?)</span></span>", text, re.S).group(1)
    for c in ("go-ethereum", "nethermind", "reth"):
        assert f'href="client-{c}.html"' in line
        assert f'>{len(snap["runs"][c]["client_wide_failures"])}</span>' in line


def m9(root, snap):
    assert "SFI+CFI in Hegotá: 8 EIPs, 8 with EELS tests, 0 without" in re.sub(r"<[^>]+>", "", visible(read(root, "index.html")))


def m10(root, snap):
    text = visible(read(root, "index.html"))
    assert '<input type="search" id="me"' in text and '<select id="mc"' in text and '<input type="checkbox" id="hp"' in text
    assert "searchParams.set('client'" in text and "searchParams.set('eip'" in text


def m11(root, snap):
    text = read(root, "index.html")
    drawer = template(text, "8253-reth")
    run = snap["runs"]["reth"]
    assert 'class="why"' in drawer and run["url"] in drawer
    assert "spec at head" in drawer and ">tests</a>" in drawer
    assert "Failed cases" in drawer and 'class="ids"' in drawer
    nm = template(text, "8141-nethermind")
    assert "Open EIP PRs" in nm and "proofs/8141-dc5d5fa6.patch" in nm and "with mutant" in nm


def e1(root, snap):
    text = visible(read(root, "eip-8141.html"))
    assert "<h1>" in text and "Frame Transaction" in text and '<span class="pill sb">SFI</span>' in text
    assert "Scheduled" in text and "EIP status Draft" in text
    for label in ("EIP text", "EELS tests", "all spec changes", "JSON"):
        assert f">{label}</a>" in text, label


def e2(root, snap):
    assert 'onclick="copyMd(this)">Copy as Markdown<' in visible(read(root, "eip-8141.html"))


def e3(root, snap):
    text = read(root, "eip-8141.html")
    for c in config.CLIENTS:
        assert f'data-open="8141-{c}"' in visible(text), c
        drawer = template(text, f"8141-{c}")
        assert 'class="why"' in drawer and f'href="index.html#8141-{c}"' in drawer


def e4(root, snap):
    text = visible(read(root, "eip-8141.html"))
    assert 'data-mark="eels-todo"' in text and ">EIP diff</a>" in text and "update tests to EIP version" in text


def e5(root, snap):
    text = visible(read(root, "eip-8141.html"))
    tl = re.search(r'<ol class="tl"[^>]*>(.*?)</ol>', text, re.S).group(1)
    assert tl.count('<li class="tli') == len(snap["eips"]["8141"]["revisions"])
    assert "dc5d5fa6" in tl and "proven" in tl


def e6(root, snap):
    text = visible(read(root, "eip-8141.html"))
    box = re.search(r'<details class="box" data-mark="pending-prs">(.*?)</details>', text, re.S).group(1)
    assert box.count("<li>") == len(snap["eips"]["8141"]["pending"])


def e7(root, snap):
    tl = re.search(r'<ol class="tl"[^>]*>(.*?)</ol>', visible(read(root, "eip-8141.html")), re.S).group(1)
    proven = re.search(r'<li class="tli ok"><details>(.*?)</details></li>', tl, re.S).group(1)
    assert "baseline" in proven and "with mutant" in proven and "killed" in proven and "command" in proven


def c1(root, snap):
    text = visible(read(root, "client-reth.html"))
    title = re.search(r'<div class="titlebar">(.*?)</div>', text, re.S).group(1)
    assert "<h1>Reth</h1>" in title and "1</span> fails" in title and "7</span> pass" in title
    assert config.CLIENT_REPO["reth"] in title and ">JSON</a>" in title


def c2(root, snap):
    text = visible(read(root, "client-reth.html"))
    todo = re.search(r'<ol class="todos">(.*?)</ol>', text, re.S).group(1)
    assert 'class="rank' in todo and "fix client" in todo and 'href="eip-8253.html"' in todo
    assert 'data-open="8253-reth"' in todo and "header_commits_to_canonical_rlp" in todo


def c3(root, snap):
    run = snap["runs"]["reth"]
    box = re.search(r'<div class="runbox">(.*)</details>', visible(read(root, "client-reth.html")), re.S).group(1)
    for v in (run["release"], run["image"], run["version"], run["url"], run["sim_log"], run["start"][:16].replace("T", " ")):
        assert v in box, v


def c4(root, snap):
    text = visible(read(root, "client-reth.html"))
    assert "48</span> failing cases in tests for EIPs this site does not track, not counted above" in text


def c5(root, snap):
    text = read(root, "client-reth.html")
    rows = re.search(r'<ul class="elist">(.*?)</ul>', visible(text), re.S).group(1)
    assert rows.count('<li class="erow">') == 8 and 'data-open="8141-reth"' in rows
    assert 'class="why"' in template(text, "8141-reth")


def c6(root, snap):
    text = visible(read(root, "client-reth.html"))
    section = text.split("Client PRs", 1)[1]
    assert "paradigmxyz/reth" in section and "not collected in this snapshot" in section


def test_drawer_is_a_modal_dialog(site):
    root, _ = site
    for name in ("index.html", "eip-8141.html", "client-reth.html"):
        assert '<aside id="d" role="dialog" aria-modal="true" aria-label="Evidence" hidden>' in read(root, name), name


def test_drawer_keeps_tab_focus_inside(site):
    root, _ = site
    script = read(root, "index.html").rsplit("<script>", 1)[1]
    assert "e.key==='Tab'" in script


def test_bad_hash_escape_does_not_stop_page_setup(site):
    root, _ = site
    script = read(root, "index.html").rsplit("<script>", 1)[1]
    assert "decodeURIComponent(location.hash" not in script


def others(root, snap):
    for name in ("queue.html", "changes.html", "divergences.html", "prs.html", "releases.html", "history.html", "start.html"):
        assert '<header class="bar">' in read(root, name), name


SIGNALS = {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6,
           "M1": m1, "M2": m2, "M3": m3, "M4": m4, "M5": m5, "M6": m6, "M7": m7, "M8": m8, "M9": m9, "M10": m10, "M11": m11,
           "E1": e1, "E2": e2, "E3": e3, "E4": e4, "E5": e5, "E6": e6, "E7": e7,
           "C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5, "C6": c6}


def test_thirty_signals_are_mapped():
    assert len(SIGNALS) == 30


@pytest.mark.parametrize("sid", sorted(SIGNALS))
def test_signal_is_at_most_one_click_away(site, sid):
    SIGNALS[sid](*site)


def test_other_pages_share_the_bar(site):
    others(*site)
