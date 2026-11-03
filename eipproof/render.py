import html
import os
import re

from . import config
from .chain import chain, headline_text, queue, release_short

E = html.escape
STATE_CLASS = {"pass": "ok", "covered": "ok", "open": "warn", "attested-not-run": "warn", "stale-release": "stale",
               "fail": "bad", "attested-failed": "bad", "no-run": "none", "no-tests": "none", "n/a": "none", "editorial": "edit",
               "draft": "draft", "covered-draft": "draft"}


def gh(repo, kind, ref):
    return f"{config.GITHUB}/{repo}/{kind}/{ref}"


def a(url, text, cls=""):
    return f'<a href="{E(url)}" target="_blank" rel="noopener"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{E(text)}</a>'


def short_test(test_id):
    return test_id.split("::", 1)[-1]


def why(cell, snap):
    h, run, test, spec = cell["headline"], cell["links"]["run"], cell["links"]["test"], cell["links"]["spec"]
    label = config.CLIENT_LABEL[cell["client"]]
    if h == "stale-release":
        return (f"{label}'s newest run used {release_short(run['release'])}; the newest release is "
                f"{release_short(run['newest_release'])}. Old tests say nothing about the current spec text, "
                f"so the old {run['passed']}/{run['total']} is shown but does not count.")
    if h == "fail":
        return f"{len(run['failed'])} test(s) in this EIP's directory failed in {label}'s run on {release_short(run['release'])}."
    if h == "open":
        n = test["open"]
        cands = [c for d in test["deltas"] for c in d["candidates"]]
        tail = ""
        if cands:
            c = cands[0]
            tail = (f" A mechanical search found {short_test(c['test'])}; its {c['passed']}/{c['cases']} cases pass here. "
                    f"It counts only after a person signs an attestation.")
        return (f"The run passed {run['passed']}/{run['total']}, but the EELS pin is {spec['behind']} revision(s) behind "
                f"the EIP head and {n} change(s) have no signed covering test yet.{tail}")
    if h == "draft":
        tests = ", ".join(t for d in test["deltas"] if d["state"] == "covered-draft" for t in d["attestation"]["tests"])
        return (f"The run passed {run['passed']}/{run['total']}. The EELS pin is {spec['behind']} revision(s) behind the EIP head, "
                f"and a draft attestation names {tests} as the covering test; it passes here. "
                f"The cell turns green when a person signs the attestation.")
    if h == "pass":
        return f"All {run['total']} tests in this EIP's directory passed on {release_short(run['release'])}, and the pin matches the EIP head or every change is covered."
    if h == "no-tests":
        return f"{label}'s run on {release_short(run['release'])} has no cases in this EIP's test directory."
    return f"No {config.SIMULATOR} run for {label}."


def dots(cell):
    out = []
    for key in ("spec", "test", "run"):
        st = cell["links"][key]["state"]
        out.append(f'<i class="dot {STATE_CLASS.get(st, "none")}" title="{key}: {E(st)}"></i>')
    return '<span class="dots">' + "".join(out) + "</span>"


def link_block(n, title, state, body):
    return (f'<section class="link {STATE_CLASS.get(state, "none")}"><header><b>{n}</b> {E(title)}'
            f'<span class="pill {STATE_CLASS.get(state, "none")}">{E(state)}</span></header>{body}</section>')


def added_lines(diff):
    return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]


def tokens_marked(text, tokens):
    out = E(text)
    for t in tokens:
        out = out.replace(E(t), f"<mark>{E(t)}</mark>")
    return out


def spec_html(cell, eip_info):
    s = cell["links"]["spec"]
    rows = [f'<div class="kv"><span>EIP head</span><code>{a(gh(config.EIPS_REPO, "commit", eip_info["head"]), eip_info["head"][:8])}</code> {E(eip_info["head_date"][:10])}</div>',
            f'<div class="kv"><span>EELS pin</span><code>{a(eip_info["pin"]["spec_py"], s["pin_blob"][:8])}</code> = EIPs '
            f'<code>{a(gh(config.EIPS_REPO, "commit", s["pin_commit"]), s["pin_commit"][:8]) if s["pin_commit"] else "?"}</code>'
            f' at {E(release_short(eip_info["pin"]["release"]))} '
            + (f'<span class="pill warn">{s["behind"]} behind</span>' if s["behind"] else '<span class="pill ok">= head</span>')
            + (' <span class="pill none">blob recurs</span>' if s["pin_ambiguous"] else "") + "</div>"]
    for p in s["pending"]:
        rows.append(f'<div class="overlay" data-mark="pending"><span class="pill none">overlay</span> {a(p["url"], "EIPs#" + str(p["number"]))} '
                    f'{E(p["title"])} <em>{E(p["state"])}, merged={str(p["merged"]).lower()}</em> &mdash; not spec yet, not counted</div>')
    return link_block(1, "Spec revision", s["state"], "".join(rows))


def test_html(cell, eip_info):
    t = cell["links"]["test"]
    if t["state"] == "n/a":
        return link_block(2, "EELS tests for the changes", "n/a",
                          '<p class="muted">n/a: this run did not use the newest release, so covering tests from it cannot be joined.</p>')
    if not t["deltas"]:
        return link_block(2, "EELS tests for the changes", "pass", '<p class="muted">The pin equals the EIP head: no spec change to cover.</p>')
    deltas = {d["commit"]: d for d in eip_info["deltas"]}
    rows = []
    for d in t["deltas"]:
        info = deltas[d["commit"]]
        diff = "".join(f'<div class="add">+ {tokens_marked(l, info["tokens"])}</div>' for l in added_lines(info["diff"]) if l.strip())
        cands = ""
        for c in d["candidates"]:
            src = f'{config.GITHUB}/{config.EELS_REPO}/blob/{eip_info["pin"]["release"].replace("@", "%40")}/{c["path"]}'
            cands += (f'<div class="cand" data-mark="candidate"><span class="pill ok">{c["passed"]}/{c["cases"]} pass here</span> candidate '
                      f'<code>{a(src, c["test"])}</code> <em>matches {", ".join(E(x) for x in c["tokens"])}</em></div>')
        att = ""
        if "attestation" in d:
            at = d["attestation"]
            sign = ' <span class="pill draft">unsigned</span>' if at.get("status") == "draft" else ""
            att = f'<div class="att" data-mark="att">attested by <b>{E(at["author"])}</b> {E(at["date"])}: {", ".join(E(x) for x in at["tests"])}{sign}</div>'
        rows.append(f'<div class="delta" data-mark="delta"><div class="kv"><span>&Delta;</span><code>{a(gh(config.EIPS_REPO, "commit", d["commit"]), d["commit"][:8])}</code> '
                    f'{E(info["date"][:10])} {E(info["subject"])} <span class="pill {STATE_CLASS.get(d["state"], "none")}">{E(d["state"])}</span></div>'
                    f'<div class="diff">{diff}</div>{cands}{att}</div>')
    return link_block(2, "EELS tests for the changes", t["state"], "".join(rows))


def run_html(cell, run_full):
    r = cell["links"]["run"]
    if r["state"] == "no-run":
        return link_block(3, "Client run (hive)", "no-run", '<p class="muted">no run</p>')
    count = f'<b class="big">{r["passed"]}/{r["total"]}</b>'
    body = [f'<div class="kv" data-mark="count"><span>result</span>{count} cases in <code>{E(eip_dir_name(cell))}</code></div>',
            f'<div class="kv" data-mark="release"><span>fixtures</span><code>{E(r["release"])}</code>'
            + (f' <span class="pill stale">newest is {E(release_short(r["newest_release"]))}</span>' if r["state"] == "stale-release" else "") + "</div>",
            f'<div class="kv"><span>image</span><code>{E(r["image"] or "?")}</code></div>',
            f'<div class="kv"><span>version</span><code>{E(r["version"])}</code></div>',
            f'<div class="kv"><span>run</span>{E(run_full["start"][:16].replace("T", " "))}Z &rarr; {a(r["url"], "hive run")} &middot; {a(run_full["sim_log"], "sim log")}</div>']
    if r["failed"]:
        body.append('<div class="fails" data-mark="fails">' + "".join(f"<div><code>{E(short_test(f))}</code></div>" for f in r["failed"][:8]) + "</div>")
    return link_block(3, "Client run (hive)", r["state"], "".join(body))


def eip_dir_name(cell):
    return cell["links"]["_dir"]


def drawer(cell, snap):
    eip_info = snap["eips"][cell["eip"]]
    run_full = snap["runs"].get(cell["client"], {})
    h = cell["headline"]
    return (f'<div class="dhead"><div><div class="muted">EIP-{cell["eip"]} &times; {E(config.CLIENT_LABEL[cell["client"]])}</div>'
            f'<div class="headline {STATE_CLASS[h]}" data-mark="headline">{E(headline_text(cell))}</div></div><button class="x" onclick="closeD()">&times;</button></div>'
            f'<p class="why" data-mark="why">{E(why(cell, snap))}</p>'
            + spec_html(cell, eip_info) + test_html(cell, eip_info) + run_html(cell, run_full))


CSS = """
:root{--bg:#0b0f17;--card:#111827;--line:#1f2937;--fg:#e5e7eb;--mut:#8b95a7;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--stale:#818cf8;--none:#4b5563;--edit:#38bdf8;--draft:#c084fc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 Inter,"DejaVu Sans",system-ui,sans-serif}
a{color:#93c5fd;text-decoration:none}a:hover{text-decoration:underline}code{font:13px "DejaVu Sans Mono",monospace;color:#cbd5e1}
header.top{display:flex;align-items:center;gap:18px;padding:16px 28px;border-bottom:1px solid var(--line)}
.brand{font-weight:800;font-size:20px;letter-spacing:.2px}.brand span{color:var(--ok)}
nav a{margin-right:14px;color:var(--mut)}nav a.on{color:var(--fg);font-weight:600}
.meta{margin-left:auto;color:var(--mut);font-size:13px;text-align:right}
main{padding:20px 28px}.strip{background:#1a1320;border:1px solid #3b1d2a;border-radius:10px;padding:8px 12px;margin-bottom:14px;font-size:13px;color:#fca5a5}
table.m{border-collapse:separate;border-spacing:6px;width:100%}th{color:var(--mut);font-weight:600;font-size:13px;text-align:left;padding:0 8px}
th.row{width:150px}th.row a{color:var(--fg);font-size:15px}th.row small{display:block;color:var(--mut);font-weight:400}
td.c{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer;transition:.15s;vertical-align:top}
td.c:hover{border-color:#475569;transform:translateY(-1px)}td.c.sel{outline:2px solid #e5e7eb}
.hl{font-weight:700;font-size:15px}.ok .hl,.hl.ok{color:var(--ok)}.warn .hl,.hl.warn{color:var(--warn)}.bad .hl{color:var(--bad)}.stale .hl{color:var(--stale)}.none .hl{color:var(--mut)}.draft .hl{color:var(--draft)}
td.c.ok{border-left:4px solid var(--ok)}td.c.warn{border-left:4px solid var(--warn)}td.c.bad{border-left:4px solid var(--bad)}td.c.stale{border-left:4px solid var(--stale)}td.c.none{border-left:4px solid var(--none)}td.c.draft{border-left:4px solid var(--draft)}
.sub{color:var(--mut);font-size:12px;margin-top:2px}.dots{float:right;margin-top:4px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-left:4px;background:var(--none)}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}.dot.stale{background:var(--stale)}.dot.edit{background:var(--edit)}.dot.draft{background:var(--draft)}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;background:#2a2112;color:var(--warn);margin-top:4px}
.legend{color:var(--mut);font-size:13px;margin:14px 6px}.legend i{margin:0 4px 0 12px}
#d{position:fixed;top:0;right:0;height:100%;width:640px;background:#0f1522;border-left:1px solid var(--line);transform:translateX(100%);transition:transform .35s ease;overflow:auto;padding:20px 24px;box-shadow:-20px 0 40px #0008}
#d.on{transform:none}.dhead{display:flex;justify-content:space-between}.x{background:none;border:0;color:var(--mut);font-size:28px;cursor:pointer}
.headline{font-size:26px;font-weight:800}.headline.ok{color:var(--ok)}.headline.warn{color:var(--warn)}.headline.bad{color:var(--bad)}.headline.stale{color:var(--stale)}.headline.none{color:var(--mut)}.headline.draft{color:var(--draft)}
.why{color:#cbd5e1;background:#151d2c;border-radius:10px;padding:10px 12px;margin:12px 0}
section.link{border:1px solid var(--line);border-left:4px solid var(--none);border-radius:10px;padding:10px 12px;margin:10px 0;background:var(--card)}
section.link.ok{border-left-color:var(--ok)}section.link.warn{border-left-color:var(--warn)}section.link.bad{border-left-color:var(--bad)}section.link.stale{border-left-color:var(--stale)}section.link.draft{border-left-color:var(--draft)}
section.link header{display:flex;gap:8px;align-items:center;font-weight:700;margin-bottom:6px}section.link header .pill{margin-left:auto}
.pill{font-size:11px;padding:1px 8px;border-radius:99px;background:#1f2937;color:var(--mut);font-weight:600}.pill.ok{background:#0f2a1a;color:var(--ok)}.pill.warn{background:#2a2112;color:var(--warn)}.pill.bad{background:#2a1212;color:var(--bad)}.pill.stale{background:#1c1d3a;color:var(--stale)}.pill.draft{background:#26173a;color:var(--draft)}
.kv{margin:3px 0}.kv>span:first-child{display:inline-block;width:78px;color:var(--mut);font-size:13px}.big{font-size:20px;color:var(--fg)}
.diff{background:#0b1220;border-radius:8px;padding:6px 10px;margin:6px 0;font-size:13px}.add{color:#bbf7d0}mark{background:#3b3412;color:#fde68a;border-radius:3px;padding:0 2px}
.cand,.att,.overlay{margin:6px 0;font-size:13.5px}.overlay{color:var(--mut)}em{color:var(--mut);font-style:normal}.muted{color:var(--mut)}
.fails{font-size:12.5px;max-height:150px;overflow:auto;background:#1a1010;border-radius:8px;padding:6px 10px}
.q{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:10px 0}.q .k{font-weight:700}.q .k.bad{color:var(--bad)}.q .k.warn{color:var(--warn)}.q .k.stale{color:var(--stale)}.q .k.draft{color:var(--draft)}
.q .act{float:right;font-size:13px;color:#0b0f17;background:var(--fg);padding:2px 10px;border-radius:99px}
"""

JS = """
function openD(id,el){document.querySelectorAll('td.c.sel').forEach(x=>x.classList.remove('sel'));if(el)el.classList.add('sel');
document.getElementById('dc').innerHTML=document.getElementById('t-'+id).innerHTML;document.getElementById('d').classList.add('on');history.replaceState(null,'','#'+id)}
function closeD(){document.getElementById('d').classList.remove('on');document.querySelectorAll('td.c.sel').forEach(x=>x.classList.remove('sel'));history.replaceState(null,'',location.pathname)}
addEventListener('keydown',e=>{if(e.key==='Escape')closeD()});
addEventListener('load',()=>{const h=location.hash.slice(1);if(h&&document.getElementById('t-'+h))openD(h,document.getElementById('c-'+h))});
"""


def page(title, nav, body, snap):
    links = "".join(f'<a href="{href}" class="{"on" if key == nav else ""}">{E(label)}</a>' for key, href, label in
                    [("matrix", "index.html", "Matrix"), ("queue", "queue.html", "Work queue")])
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{E(title)}</title><style>{CSS}</style></head><body>'
            f'<header class="top"><div class="brand">{E(config.NAME)}<span>.</span></div><nav>{links}</nav>'
            f'<div class="meta">fork <b>{E(config.FORK)}</b> &middot; EL &middot; newest EELS release {a(snap["release_url"], snap["newest_release"])}<br>'
            f'snapshot {E(snap["taken_at"])} &middot; {a(snap["listing_url"], "hive listing")} ({snap["listing_rows"]} runs)</div></header>'
            f'<main>{body}</main><aside id="d"><div id="dc"></div></aside><script>{JS}</script></body></html>')


def cells_for(snap, attestations):
    cells = []
    for eip in config.ROW_ORDER:
        if eip not in snap["eips"]:
            continue
        for client in config.CLIENTS:
            cell = chain(eip, client, snap, attestations)
            cell["links"]["_dir"] = snap["eips"][eip]["test_dir"].rsplit("/", 1)[-1]
            cells.append(cell)
    return cells


def cell_sub(cell):
    r = cell["links"]["run"]
    if cell["headline"] == "stale-release":
        return f"old {r['passed']}/{r['total']} &middot; newest {E(release_short(r['newest_release']))}"
    if cell["headline"] in ("open", "draft"):
        return f"run {r['passed']}/{r['total']} &middot; pin {cell['links']['spec']['behind']} behind"
    if r.get("image"):
        return E(r["image"].rsplit(":", 1)[-1].replace("-linux-amd64", ""))
    return ""


def matrix_html(snap, cells):
    by = {(c["eip"], c["client"]): c for c in cells}
    head = "<tr><th></th>" + "".join(f"<th>{E(config.CLIENT_LABEL[c])}<br><small class=muted>{E(release_short(snap['runs'][c]['release']) if c in snap['runs'] else '-')}</small></th>" for c in config.CLIENTS) + "</tr>"
    rows, templates = [], []
    for eip in config.ROW_ORDER:
        if eip not in snap["eips"]:
            continue
        info = snap["eips"][eip]
        badge = f'<div class="badge">open &Delta;{len(info["deltas"])}</div>' if info["deltas"] else ""
        pend = f'<div class="badge" style="background:#1f2937;color:#8b95a7">{len(info["pending"])} open PR overlay</div>' if info["pending"] else ""
        tr = [f'<th class="row">{a(f"{config.GITHUB}/{config.EIPS_REPO}/blob/{config.EIPS_BRANCH}/{info["path"]}", "EIP-" + eip)}<small>{E(info["test_dir"].rsplit("/", 1)[-1].split("_", 1)[1].replace("_", " "))}</small>{badge}{pend}</th>']
        for client in config.CLIENTS:
            c = by[(eip, client)]
            cid = f"{eip}-{client}"
            tr.append(f'<td class="c {STATE_CLASS[c["headline"]]}" id="c-{cid}" onclick="openD(\'{cid}\',this)">{dots(c)}<div class="hl">{E(headline_text(c))}</div><div class="sub">{cell_sub(c)}</div></td>')
            templates.append(f'<template id="t-{cid}">{drawer(c, snap)}</template>')
        rows.append("<tr>" + "".join(tr) + "</tr>")
    strip = ""
    wide = {c: r["client_wide_failures"] for c, r in snap["runs"].items() if r["client_wide_failures"] and r["release"] == snap["newest_release"]}
    if wide:
        strip = '<div class="strip">client-wide failures outside EIP dirs (not counted in cells): ' + " &middot; ".join(
            f'{E(config.CLIENT_LABEL[c])} {len(v)}' for c, v in wide.items()) + "</div>"
    legend = ('<div class="legend">each cell = weakest link of <b>spec &middot; test &middot; run</b>'
              '<i class="dot ok"></i>pass<i class="dot warn"></i>open change<i class="dot draft"></i>needs sign-off<i class="dot stale"></i>stale release<i class="dot bad"></i>fail<i class="dot"></i>n/a</div>')
    return strip + f'<table class="m">{head}{"".join(rows)}</table>' + legend + "".join(templates)


def queue_html(snap, cells):
    items = queue(cells, config.ROW_ORDER)
    out = ['<h2 style="margin:4px 0 12px">Work queue <span class="muted" style="font-size:14px;font-weight:400">every broken link is one next action</span></h2>']
    for i, it in enumerate(items, 1):
        clients = ", ".join(config.CLIENT_LABEL[c] for c in it["clients"])
        if it["kind"] == "open-delta":
            info = snap["eips"][it["eip"]]
            delta = next(d for d in info["deltas"] if d["commit"] == it["commit"])
            cands = "".join(f'<div class="cand"><code>{E(t)}</code> <em>passes on: {", ".join(f"{config.CLIENT_LABEL[c]} {p}/{n}" for c, (p, n) in v.items())}</em></div>' for t, v in it["candidates"].items())
            body = (f'<span class="k warn">EIP-{it["eip"]} &middot; open &Delta;</span> {a(gh(config.EIPS_REPO, "commit", it["commit"]), it["commit"][:8])} {E(delta["subject"])}'
                    f'<div class="muted">affects {E(clients)}</div>{cands}')
        elif it["kind"] == "run-fail":
            body = (f'<span class="k bad">EIP-{it["eip"]} &middot; fail</span> {E(clients)}: {len(it["failed"])} failing'
                    + "".join(f'<div><code>{E(short_test(f))}</code></div>' for f in it["failed"][:3]))
        elif it["kind"] == "sign-attestation":
            body = (f'<span class="k draft">EIP-{it["eip"]} &middot; draft attestation</span> {a(gh(config.EIPS_REPO, "commit", it["commit"]), it["commit"][:8])} '
                    + " ".join(f'<code>{E(t)}</code>' for t in it["tests"]) + f'<div class="muted">affects {E(clients)}</div>')
        else:
            body = f'<span class="k stale">EIP-{it["eip"]} &middot; stale-release</span> {E(clients)} last ran {E(release_short(it["release"]))}'
        cid = f'{it["eip"]}-{it["clients"][0]}'
        out.append(f'<div class="q" id="q{i}"><a class="act" href="index.html#{cid}">{E(it["action"])}</a>{body}</div>')
    return "".join(out), items


def site(snap, attestations, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cells = cells_for(snap, attestations)
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(page(f"{config.NAME} · {config.FORK}", "matrix", matrix_html(snap, cells), snap))
    qbody, items = queue_html(snap, cells)
    with open(os.path.join(out_dir, "queue.html"), "w") as f:
        f.write(page(f"{config.NAME} · queue", "queue", qbody, snap))
    return cells, items
