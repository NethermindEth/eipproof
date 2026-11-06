import html
import json
import os
import re
from datetime import datetime

from . import build, codepr, config, diverge, handoff, impact, index
from .chain import EELS, cell_action, chain, delta_verbs, eels_action, eels_todo, headline_text, queue, release_short

E = html.escape
STATE_CLASS = {"pass": "ok", "covered": "ok", "open": "warn", "attested-not-run": "warn", "stale-release": "stale",
               "fail": "bad", "attested-failed": "bad", "no-run": "none", "no-tests": "none", "n/a": "none", "editorial": "edit",
               "mutant-survived": "warn"}
LABEL = {"pass": "ok", "covered": "proven", "open": "untested", "attested-not-run": "proof test missing", "stale-release": "old tests",
         "fail": "fails", "attested-failed": "proof test fails", "no-run": "no run", "no-tests": "no tests", "n/a": "n/a",
         "editorial": "wording only", "mutant-survived": "no test catches it"}
DOT = {"spec": "spec change", "test": "test proof", "run": "client run"}


def gh(repo, kind, ref):
    return f"{config.GITHUB}/{repo}/{kind}/{ref}"


GLYPH = {"ok": "✓", "bad": "✕", "stale": "◷", "warn": "?", "none": "–", "edit": "–"}


def url_attr(url):
    return E(url).replace("&amp;", "&")


def a(url, text, cls=""):
    return f'<a href="{url_attr(url)}" target="_blank" rel="noopener"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{E(text)}</a>'


def glyph(cls):
    return f'<span class="g" aria-hidden="true">{GLYPH[cls]}</span>'


def chip(cls, text, extra=""):
    return f'<span class="chip {cls}{extra}">{glyph(cls)}<span class="n">{E(text)}</span></span>'


def kv(key, value):
    return f'<div class="kv"><span class="k">{E(key)}</span><span class="v">{value}</span></div>'


def json_link(href):
    return f'<a class="jsn" href="{E(href)}">JSON</a>'


def titlebar(h1, extra="", json_href=""):
    return f'<div class="titlebar"><h1>{h1}</h1>{extra}{json_link(json_href) if json_href else ""}</div>'


def short_test(test_id):
    return test_id.split("::", 1)[-1]


def why(cell, snap):
    h, run, test, spec = cell["headline"], cell["links"]["run"], cell["links"]["test"], cell["links"]["spec"]
    label = config.CLIENT_LABEL[cell["client"]]
    if h == "stale-release":
        return (f"{label}'s newest run used tests {release_short(run['release'])}, but the newest EELS release is "
                f"{release_short(run['newest_release'])}. Old tests do not check the current spec, "
                f"so the old {run['passed']}/{run['total']} is shown but does not count. Next: run {release_short(run['newest_release'])}.")
    if h == "fail":
        return f"{plural(len(run['failed']), 'test')} for this EIP failed in {label}'s run on {release_short(run['release'])}. Next: fix the client or report the test."
    if h == "open":
        n = test["open"]
        cands = [c for d in test["deltas"] for c in d["candidates"]]
        tail = ""
        if cands:
            c = cands[0]
            tail = (f" Likely test: {short_test(c['test'])} ({c['passed']}/{c['cases']} pass here). "
                    f"It counts once a mutant that undoes the change makes one of its cases fail.")
        survived = any(d["state"] == "mutant-survived" for d in test["deltas"])
        gap = "no test catches a spec that undoes them" if survived else "no proof yet"
        nxt = "write a test that fails without the change" if survived else "run `eipproof prove` with a mutant that undoes the change"
        return (f"The run passed {run['passed']}/{run['total']}, but the EIP text changed {plural(spec['behind'], 'time')} since the "
                f"version EELS implements, and {plural(n, 'change')} {'has' if n == 1 else 'have'} {gap}.{tail} Next: {nxt}.")
    if h == "pass":
        proven = [d for d in test["deltas"] if d["state"] == "covered"]
        if proven:
            return (f"All {run['total']} tests for this EIP passed on {release_short(run['release'])}. "
                    f"The EIP text changed {plural(spec['behind'], 'time')} since the version EELS implements. For each change, a spec "
                    f"with the change undone fails {', '.join(str(d['cases']) for d in proven)} {'case' if [d['cases'] for d in proven] == [1] else 'cases'} in EELS, and those cases pass here.")
        return f"All {run['total']} tests for this EIP passed on {release_short(run['release'])}, and EELS implements the current EIP text."
    if h == "no-tests":
        return f"{label}'s run on {release_short(run['release'])} has no cases in this EIP's test directory."
    return f"No {config.SIMULATOR} run for {label}."


def run_count(cell):
    r = cell["links"]["run"]
    return f'{r["passed"]}/{r["total"]}' if r.get("total") is not None else LABEL.get(cell["headline"], cell["headline"])


def md(url, text):
    return f"[{text}]({url})"


def copy_md(text, label="Copy as Markdown"):
    return (f'<div class="copy"><button type="button" class="btn" onclick="copyMd(this)">{E(label)}</button>'
            f'<textarea class="md" readonly hidden aria-label="Markdown">{E(text)}</textarea></div>')


def cell_markdown(cell, snap):
    info = snap["eips"][cell["eip"]]
    s, t, r = cell["links"]["spec"], cell["links"]["test"], cell["links"]["run"]
    subjects = {d["commit"]: d["subject"] for d in info["deltas"]}
    pin = md(gh(config.EIPS_REPO, "commit", s["pin_commit"]), s["pin_commit"][:8]) if s["pin_commit"] else "?"
    lines = [f'**EIP-{cell["eip"]} x {config.CLIENT_LABEL[cell["client"]]}: {headline_text(cell)}**', "", why(cell, snap), "",
             f'- Spec: EIP now {md(gh(config.EIPS_REPO, "commit", info["head"]), info["head"][:8])}; EELS '
             f'{release_short(info["pin"]["release"])} implements {pin}' + (f', {plural(s["behind"], "change")} behind' if s["behind"] else ", current")]
    if t["state"] != "n/a":
        for d in t.get("deltas", []):
            at = d.get("attestation") or {}
            proof = f' ({md(f"{config.GITHUB}/{config.SELF_REPO}/blob/main/proofs/{at["mutant"]}", "mutant")})' if at.get("mutant") else ""
            lines.append(f'- Spec change {md(gh(config.EIPS_REPO, "commit", d["commit"]), d["commit"][:8])} '
                         f'{subjects.get(d["commit"], "")}: {LABEL.get(d["state"], d["state"])}{proof}')
    if r["state"] == "no-run":
        lines.append(f"- Run: no {config.SIMULATOR} run")
    else:
        lines.append(f'- Run: {r["passed"]}/{r["total"]} on `{r["release"]}`, {md(r["url"], "hive run")}')
    lines.append(f'- Source: {md(f"{config.SITE_URL}/index.html#{cell["eip"]}-{cell["client"]}", config.NAME)}, snapshot {snap["taken_at"]}')
    return "\n".join(lines) + "\n"


def eip_markdown(eip, snap, cells, attestations):
    info = snap["eips"][eip]
    lines = [f'**EIP-{eip} {eip_name(info)}** ({config.NAME}, fork {config.FORK}, snapshot {snap["taken_at"]})', ""]
    for c in cells:
        if c["eip"] == eip:
            lines.append(f'- {config.CLIENT_LABEL[c["client"]]}: {headline_text(c)}. {why(c, snap)} '
                         f'{md(f"{config.SITE_URL}/index.html#{eip}-{c["client"]}", "evidence")}')
    todo = eels_item(eip, snap)
    if todo:
        lines.append(f'- EELS: {todo["action"]}. {eels_detail(todo, snap)} ' + (md(todo["diff_url"], "EIP diff") if todo.get("diff_url") else ""))
    lines += ["", "Spec changes, newest first:"]
    for rev in reversed(info["revisions"]):
        lines.append(f'- {md(gh(config.EIPS_REPO, "commit", rev["commit"]), rev["commit"][:8])} {rev["date"][:10]} '
                     f'{rev["subject"]}: {rev_state(eip, info, rev, attestations)[1]}')
    lines += ["", f'{md(f"{config.GITHUB}/{config.EIPS_REPO}/blob/{config.EIPS_BRANCH}/{info["path"]}", "EIP text")} · '
                  f'{md(f"{config.SITE_URL}/{eip_href(eip)}", "eipproof page")}']
    return "\n".join(lines) + "\n"


def check_block(name, state, body):
    return (f'<section class="check"><div class="chead"><span class="cname">{E(name)}</span>'
            f'{chip(STATE_CLASS.get(state, "none"), LABEL.get(state, state))}</div><div class="cbody">{body}</div></section>')


def added_lines(diff):
    return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]


def tokens_marked(text, tokens):
    out = E(text)
    for t in tokens:
        out = out.replace(E(t), f"<mark>{E(t)}</mark>")
    return out


def spec_html(cell, eip_info, snap):
    s = cell["links"]["spec"]
    rows = [kv("EIP now", f'<code>{a(gh(config.EIPS_REPO, "commit", eip_info["head"]), eip_info["head"][:8])}</code> {E(eip_info["head_date"][:10])}'),
            kv("EELS has", f'<code>{a(eip_info["pin"]["spec_py"], s["pin_blob"][:8])}</code> = EIPs '
               f'<code>{a(gh(config.EIPS_REPO, "commit", s["pin_commit"]), s["pin_commit"][:8]) if s["pin_commit"] else "?"}</code>'
               f' at {E(release_short(eip_info["pin"]["release"]))} '
               + (f'<span class="pill warn">{plural(s["behind"], "change")} behind</span>' if s["behind"] else '<span class="pill ok">current</span>')
               + (' <span class="pill none">same text in several commits</span>' if s["pin_ambiguous"] else ""))]
    return check_block("Spec change", s["state"], "".join(rows))


def test_html(cell, eip_info):
    t = cell["links"]["test"]
    if t["state"] == "n/a":
        return check_block("Test proof", "n/a", '<p class="muted">n/a: this run used old tests, so proofs for the current tests do not apply.</p>')
    if not t["deltas"]:
        return check_block("Test proof", "pass", '<p class="muted">EELS implements the current EIP text: no change to prove.</p>')
    deltas = {d["commit"]: d for d in eip_info["deltas"]}
    rows = []
    for d in t["deltas"]:
        info = deltas[d["commit"]]
        diff = "".join(f'<div class="add">+ {tokens_marked(l, info["tokens"])}</div>' for l in added_lines(info["diff"]) if l.strip())
        cands = ""
        for c in d["candidates"]:
            src = f'{config.GITHUB}/{config.EELS_REPO}/blob/{eip_info["pin"]["release"].replace("@", "%40")}/{c["path"]}'
            cands += (f'<div class="cand" data-mark="candidate"><span class="pill ok">{c["passed"]}/{c["cases"]} pass here</span> likely test '
                      f'<code>{a(src, c["test"])}</code> <em>shares words {", ".join(E(x) for x in c["tokens"])}</em></div>')
        att = proof_html(d.get("attestation"))
        rows.append('<div class="delta" data-mark="delta">' + kv("change", f'<code>{a(gh(config.EIPS_REPO, "commit", d["commit"]), d["commit"][:8])}</code> '
                    f'{E(info["date"][:10])} {E(info["subject"])} <span class="pill {STATE_CLASS.get(d["state"], "none")}">{E(LABEL.get(d["state"], d["state"]))}</span>')
                    + f'{constants_html(info)}<div class="diff">{diff}</div>{cands}{att}</div>')
    return check_block("Test proof", t["state"], "".join(rows))


def proof_html(at):
    if not at:
        return ""
    if at.get("kind") == "editorial":
        return f'<div class="att" data-mark="att">wording only, no behaviour: {E(at.get("reason", at.get("note", "")))}</div>'
    if "killed" not in at:
        return ""
    mutant = a(f'{config.GITHUB}/{config.SELF_REPO}/blob/main/proofs/{at["mutant"]}', "mutant")
    if not at["killed"]:
        return (f'<div class="att" data-mark="att"><span class="pill warn">no test catches it</span> a {mutant} undoes the change and all '
                f'{at["with_mutant"]["passed"]}/{at["with_mutant"]["cases"]} cases still pass in EELS {E(release_short(at["eels"]["ref"]))}</div>')
    b, w = at["baseline"], at["with_mutant"]
    return (f'<div class="att" data-mark="att"><span class="pill ok">proven</span> a {mutant} undoes the change; in EELS '
            f'{E(release_short(at["eels"]["ref"]))} it fails {len(at["killed"])} of {b["cases"]} cases <em>({E(at["date"])})</em>'
            + kv("baseline", f'<span class="num">{b["passed"]}/{b["cases"]}</span> pass')
            + kv("with mutant", f'<span class="num">{w["passed"]}/{w["cases"]}</span> pass')
            + kv("killed", f'<span class="num">{len(at["killed"])}</span>{ids_list(at["killed"])}')
            + kv("EELS", f'{E(at["eels"]["ref"])} <code>{a(gh(at["eels"]["repo"], "commit", at["eels"]["commit"]), at["eels"]["commit"][:8])}</code>')
            + f'<div class="cmd"><span class="k">command</span><code>{E(at["command"])}</code></div></div>')


def ids_list(ids):
    return '<ul class="ids">' + "".join(f"<li><code>{E(short_test(i))}</code></li>" for i in ids) + "</ul>"


def run_html(cell, run_full):
    r = cell["links"]["run"]
    if r["state"] == "no-run":
        return check_block("Client run", "no-run", '<p class="muted">no run</p>')
    body = [kv("result", f'<b class="num">{r["passed"]}/{r["total"]}</b> cases in <code>{E(eip_dir_name(cell))}</code>'),
            kv("tests", f'<code>{E(r["release"])}</code>'
               + (f' <span class="pill stale">newest is {E(release_short(r["newest_release"]))}</span>' if r["state"] == "stale-release" else "")),
            kv("image", f'<code>{E(r["image"] or "?")}</code>'),
            kv("version", f'<code>{E(r["version"])}</code>'),
            kv("run", f'{E(run_full["start"][:16].replace("T", " "))}Z &rarr; {a(r["url"], "hive run")} &middot; {a(run_full["sim_log"], "sim log")}')]
    return check_block("Client run", r["state"], "".join(body))


def eip_dir_name(cell):
    return cell["links"]["_dir"]


def image_tag(image):
    return image.rsplit(":", 1)[-1].replace("-linux-amd64", "") if image else ""


def test_dir_url(release, test_dir):
    return f'{config.GITHUB}/{config.EELS_REPO}/tree/{release.replace("@", "%40")}/{test_dir}'


def drawer_head(eip, who, title):
    return (f'<div class="dh"><div><div class="dt">EIP-{E(eip)} &middot; {E(who)}</div><div class="dsub">{E(title)}</div></div>'
            f'<button type="button" class="x" data-close aria-label="Close">&times;</button></div>')


def next_line(verb, owner):
    return '<div class="next"><span class="k">Next</span> ' + (f'<b>{E(verb)}</b> &middot; owner {E(owner)}' if verb else "nothing to do") + '</div>'


def pending_block(rows):
    if not rows:
        return ""
    return f'<h3>Open EIP PRs <span class="num">{len(rows)}</span> <span class="muted">not merged, not counted</span></h3>{pending_html(rows)}'


def drawer(cell, snap):
    eip, client = cell["eip"], cell["client"]
    eip_info = snap["eips"][eip]
    run_full = snap["runs"].get(client, {})
    h, r, s = cell["headline"], cell["links"]["run"], cell["links"]["spec"]
    tag = image_tag(r.get("image"))
    links = [a(r["url"], "hive run")] if r.get("url") else []
    links.append(a(f'{config.GITHUB}/{config.EIPS_REPO}/blob/{eip_info["head"]}/{eip_info["path"]}', "spec at head"))
    if s["behind"] and s["pin_commit"]:
        links.append(a(f'{config.GITHUB}/{config.EIPS_REPO}/compare/{s["pin_commit"]}...{eip_info["head"]}', "spec diff"))
    if r.get("release"):
        links.append(a(test_dir_url(r["release"], eip_info["test_dir"]), "tests"))
    links += [f'<a href="index.html#{eip}-{client}">in status grid</a>', a_local(eip_href(eip), "EIP page"), a_local(f"api/eip/{eip}.json", "JSON")]
    failed = r.get("failed") or []
    return (drawer_head(eip, config.CLIENT_LABEL[client], eip_info.get("title") or eip_name(eip_info))
            + f'<div class="dbig">{chip(STATE_CLASS[h], run_count(cell), " big")}<span class="dhl" data-mark="headline">{E(headline_text(cell))}</span>'
            + (f'<span class="tag" title="devnet image tag">{E(tag)}</span>' if tag else "") + '</div>'
            + f'<p class="why" data-mark="why">{E(why(cell, snap))}</p>'
            + next_line(cell_action(cell, snap["newest_release"]), config.CLIENT_LABEL[client])
            + f'<div class="dlinks">{" ".join(links)}</div>'
            + copy_md(cell_markdown(cell, snap))
            + (copy_md(handoff.brief_markdown(handoff.brief(cell, snap, why(cell, snap))), "Copy implement brief") if h != "pass" else "")
            + (f'<h3>Failed cases <span class="num">{len(failed)}</span></h3>{ids_list(failed)}' if failed else "")
            + '<h3>Three checks</h3>' + spec_html(cell, eip_info, snap) + test_html(cell, eip_info) + run_html(cell, run_full)
            + pending_block(handoff.pending_spec(snap, eip)))


CSS = """
:root{--ink:#14171c;--mut:#5b6472;--bd:#e3e6ea;--bg:#fff;--sf:#f6f7f9;--ok:#0b7a5a;--bad:#c2410c;--stale:#b45309;--warn:#6d28d9;--none:#6b7280;--focus:#1d4ed8;
--sans:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,"DejaVu Sans Mono",monospace;--r:6px}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;font:14px/1.45 var(--sans);color:var(--ink);background:var(--bg)}
a{color:inherit;text-decoration:underline;text-decoration-color:#b9c0c9;text-underline-offset:2px}
a:hover{text-decoration-color:var(--ink)}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}
[hidden]{display:none!important}
.num,.n{font-variant-numeric:tabular-nums}
.mono,code{font-family:var(--mono);font-size:12px}
.muted,em{color:var(--mut);font-style:normal}
.small{font-size:12px;font-weight:400}
.sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;border:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
p{overflow-wrap:break-word}
.bar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:16px;height:48px;padding:0 16px;background:var(--bg);border-bottom:1px solid var(--bd)}
.brand{font-weight:600;text-decoration:none;font-size:15px}
.forks{display:flex;border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;flex:none}
.forks a{padding:4px 10px;text-decoration:none;color:var(--mut);font-size:13px}
.forks a+a{border-left:1px solid var(--bd)}
.forks a.on{background:var(--ink);color:#fff}
.pnav{display:flex;align-items:center;gap:4px;flex:1}
.pnav>a,.pnav>.pop>summary{padding:6px 10px;border-radius:var(--r);text-decoration:none;color:var(--ink);cursor:pointer}
.pnav>a:hover,.pnav>.pop>summary:hover{background:var(--sf)}
.pnav>a.on{font-weight:600;box-shadow:inset 0 -2px 0 var(--ink);border-radius:0}
.menu,.qk{display:none}
.pop{position:relative}
.pop>summary{list-style:none;user-select:none}
.pop>summary::-webkit-details-marker{display:none}
.pnav .pop>summary::after{content:"";display:inline-block;margin-left:6px;border:4px solid transparent;border-top-color:currentColor;transform:translateY(2px)}
.panel{position:absolute;z-index:40;top:calc(100% + 6px);left:0;min-width:220px;background:var(--bg);border:1px solid var(--bd);border-radius:var(--r);box-shadow:0 6px 24px rgba(20,23,28,.12);padding:8px;color:var(--ink);font-size:13px}
.panel.right{left:auto;right:0;width:360px}
.panel.wide{width:380px}
.panel p{margin:4px 0 8px}
.panel.list{display:flex;flex-direction:column;padding:4px}
.panel.list a{display:flex;justify-content:space-between;gap:16px;padding:8px;border-radius:4px;text-decoration:none}
.panel.list a:hover{background:var(--sf)}
.snap{margin-left:auto}
.schip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border:1px solid currentColor;border-radius:999px;font-size:13px;cursor:pointer;white-space:nowrap}
.schip>span:not(.g){color:var(--ink)}
.schip.old{color:var(--stale);background:#fdf6ec}
.schip.ok{color:var(--ok)}
.asof{margin:0 0 6px}
p.stale{margin:6px 0 0;color:var(--stale)}
.kv{display:grid;grid-template-columns:110px 1fr;gap:8px;padding:4px 0;border-top:1px solid var(--bd);font-size:13px}
.kv:first-child{border-top:0}
.k{color:var(--mut)}
.kv .v{min-width:0;overflow-wrap:anywhere}
main{padding:16px 16px 48px;max-width:1440px;margin:0 auto}
.titlebar{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px;margin:0 0 8px}
h1{font-size:20px;line-height:1.25;margin:0;font-weight:600;text-wrap:balance}
h2{font-size:15px;font-weight:600;margin:24px 0 8px}
h3{font-size:13px;font-weight:600;margin:16px 0 6px}
.jsn{font-size:13px;color:var(--mut)}
.titlebar .jsn{margin-left:auto}
.crumbs{font-size:13px;color:var(--mut);margin-bottom:4px}
.facts{display:flex;flex-wrap:wrap;gap:4px 24px;font-size:13px;color:var(--mut);margin-bottom:8px}
.ut{margin-left:6px;color:var(--ink)}
.ut .num{font-weight:600;color:var(--bad)}
.strip{padding:8px 12px;margin-bottom:12px;border:1px solid #e7c48f;border-radius:var(--r);background:#fdf6ec;font-size:13px}
.tools{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:8px 0 12px}
.find{display:inline-flex;flex-wrap:wrap;align-items:center;gap:8px}
input[type=search],select{font:inherit;height:32px;padding:0 8px;border:1px solid var(--bd);border-radius:var(--r);background:var(--bg);color:var(--ink)}
.find input[type=search]{width:220px}
label{font-size:13px;color:var(--mut)}
.find label{display:inline-flex;align-items:center;gap:6px}
.tog{display:inline-flex;border:1px solid var(--bd);border-radius:var(--r);overflow:hidden}
.tog button{font:inherit;font-size:13px;background:var(--bg);color:var(--mut);border:0;padding:5px 12px;cursor:pointer}
.tog button+button{border-left:1px solid var(--bd)}
.tog button[aria-pressed="true"]{background:var(--ink);color:#fff}
.legend{display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;font-size:12px;color:var(--mut)}
.tools .legend{margin-left:auto}
.legend .panel{left:auto;right:0}
.lg .g,.cnt .g,.tw .g,.rel .g{font-weight:700}
.lg.ok .g,.cnt.ok .g,.tw.ok .g{color:var(--ok)}.lg.bad .g,.cnt.bad .g,.tw.bad .g{color:var(--bad)}.lg.stale .g,.cnt.stale .g,.rel .g{color:var(--stale)}.lg.warn .g,.cnt.warn .g,.tw.warn .g{color:var(--warn)}.lg.none .g,.cnt.none .g,.tw.none .g{color:var(--none)}
.legend summary{cursor:pointer;color:var(--ink);text-decoration:underline;text-decoration-color:#b9c0c9;text-underline-offset:2px}
.pill{display:inline-block;padding:0 6px;border:1px solid var(--bd);border-radius:4px;font-size:11px;font-weight:600;line-height:16px;color:var(--mut);background:var(--sf)}
.pill.sb{border-color:var(--ink);color:var(--ink);background:var(--bg);margin-right:4px}
.pill.ok{color:var(--ok);border-color:#9fd3c1;background:#f0f8f5}.pill.bad{color:var(--bad);border-color:#f0b9a0;background:#fdf1ec}
.pill.warn{color:var(--warn);border-color:#c9b6f2;background:#f6f2fd}.pill.stale{color:var(--stale);border-color:#e7c48f;background:#fdf6ec}
.nb{display:inline-flex;align-items:center;gap:2px;padding:0 5px;border-radius:4px;font-size:11px;line-height:16px;background:var(--sf);border:1px solid var(--bd);color:var(--ink)}
.nb.p{border-style:dashed;color:var(--mut)}
.hl.ok{color:var(--ok)}.hl.bad{color:var(--bad)}.hl.stale{color:var(--stale)}.hl.warn{color:var(--warn)}.hl.none{color:var(--mut)}
.wrap{position:relative;overflow-x:auto;border:1px solid var(--bd);border-radius:var(--r)}
table.m{border-collapse:separate;border-spacing:0;width:100%}
table.m th,table.m td{padding:4px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:middle}
table.m tr:last-child>*{border-bottom:0}
table.m:not(.list){min-width:860px}
table.m:not(.list) thead th{background:var(--sf);font-weight:600}
table.m:not(.list) th.row{position:sticky;left:0;z-index:2;background:var(--bg);min-width:240px;max-width:300px;border-right:1px solid var(--bd);font-weight:400}
.corner{position:sticky;left:0;z-index:3;font-size:12px;color:var(--mut)}
.ch{white-space:nowrap;padding:8px!important}
.ch a{text-decoration:none}
.ch a:hover{text-decoration:underline}
.rel{display:block;font-weight:400;color:var(--mut);font-size:11px;font-family:var(--mono)}
.rel.oldrel{color:var(--stale);font-weight:600}
.ch.eels,td.c.eels{border-left:1px solid var(--bd)}
.sums>*{background:var(--sf);font-size:12px}
table.m:not(.list) .sums th.row{background:var(--sf);color:var(--mut)}
.sum{white-space:nowrap}
.cnt{display:inline-flex;align-items:center;gap:2px;margin-right:6px}
.eipn{font-weight:600;text-decoration:none;font-variant-numeric:tabular-nums}
.eipn:hover{text-decoration:underline}
th.row .tt{font-weight:400}
.r2{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;margin-top:2px;font-size:12px;color:var(--mut)}
.chip{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:32px;min-width:96px;width:100%;padding:0 8px;border:1px solid;border-radius:var(--r);font:inherit;font-size:13px;color:var(--ink);background:var(--bg);white-space:nowrap}
button.chip{cursor:pointer}
button.chip:hover{box-shadow:0 0 0 1px currentColor inset}
.chip .st{display:inline-flex;align-items:center;gap:6px}
.chip .g{font-weight:700;font-size:14px;line-height:1}
.chip.ok{border-color:#9fd3c1;background:#f0f8f5}.chip.ok .g{color:var(--ok)}
.chip.bad{border-color:var(--bad);background:var(--bad);color:#fff}.chip.bad .g{color:#fff}
.chip.stale{border-color:#e7c48f;background:#fdf6ec}.chip.stale .g{color:var(--stale)}
.chip.warn{border-color:#c9b6f2;background:#f6f2fd}.chip.warn .g{color:var(--warn)}
.chip.none,.chip.edit{border-color:var(--bd);background:var(--sf);color:var(--mut)}.chip.none .g,.chip.edit .g{color:var(--none)}
.chip.sel{outline:2px solid var(--ink);outline-offset:1px}
.check .chip,.todo .chip,.runbox .chip,.card .chip{width:auto;min-width:0;height:22px;font-size:12px;padding:0 6px}
td.c .ac{display:none;flex-direction:column;align-items:flex-start;text-align:left;line-height:1.2}
body.act td.c .ac{display:flex}body.act td.c .st{display:none}
body.act td.c button.chip{height:auto;min-height:32px;padding:4px 8px;justify-content:flex-start}
.ac .hl{font-weight:600}.ac .hl.av{color:inherit}.ac .sub{font-size:11px;opacity:.8}
td.c.none[data-mark="no-tests"]{color:var(--mut);font-size:12px}
td.c.none[data-mark="no-tests"] .hl{color:var(--ink);font-weight:600;font-size:13px}
table.list td.c.ok{background:#f0f8f5}table.list td.c.bad{background:#fdf1ec}table.list td.c.warn{background:#f6f2fd}table.list td.c.stale{background:#fdf6ec}table.list td.c.none{background:var(--sf);color:var(--mut)}
table.list td.c a.hl{font-weight:600;text-decoration:none}
table.list th.row{font-weight:600;width:180px;vertical-align:top}
table.list th small,table.m th.row small{display:block;font-weight:400;color:var(--mut);font-size:12px}
.sub{color:var(--mut);font-size:12px;overflow-wrap:anywhere}
.empty{padding:16px}
.scrim{position:fixed;inset:0;z-index:45;background:rgba(20,23,28,.32)}
#d{position:fixed;z-index:50;top:48px;right:0;bottom:0;width:460px;max-width:100vw;background:var(--bg);border-left:1px solid var(--bd);box-shadow:-8px 0 24px rgba(20,23,28,.08);overflow-y:auto;padding:0 16px 24px}
.dh{position:sticky;top:0;z-index:1;display:flex;justify-content:space-between;gap:8px;padding:12px 0 8px;background:var(--bg);border-bottom:1px solid var(--bd)}
.dt{font-weight:600;font-size:15px}
.dsub{color:var(--mut);font-size:13px}
.x{width:32px;height:32px;border:1px solid var(--bd);border-radius:var(--r);background:var(--bg);cursor:pointer;font-size:18px;line-height:1;color:var(--ink);flex:none}
.dbig{display:flex;align-items:center;gap:8px;margin:12px 0 8px;flex-wrap:wrap}
.chip.big{width:auto;height:36px;font-size:15px;padding:0 12px}
.dhl{font-weight:600}
.tag{padding:1px 6px;background:var(--sf);border:1px solid var(--bd);border-radius:4px;font-size:11px;font-family:var(--mono)}
.why{margin:8px 0;text-wrap:pretty}
.next{padding:8px;background:var(--sf);border-radius:var(--r);font-size:13px}
.dlinks{display:flex;flex-wrap:wrap;gap:4px 12px;margin:8px 0;font-size:13px}
.check{border:1px solid var(--bd);border-radius:var(--r);margin:8px 0;padding:8px}
.chead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px}
.cname{font-weight:600;font-size:13px}
.cbody{font-size:13px}
.cbody p{margin:4px 0}
.delta+.delta{margin-top:8px;padding-top:8px;border-top:1px dashed var(--bd)}
.diff{background:var(--sf);border-radius:4px;padding:6px 8px;margin:6px 0;font-size:12px;font-family:var(--mono);overflow-wrap:anywhere}
.add{color:var(--ok)}
mark{background:#fdf0c4;color:inherit;border-radius:3px;padding:0 2px}
.cand,.att{margin:6px 0;font-size:13px}
.att{padding-top:4px;border-top:1px dashed var(--bd)}
.cmd{padding:4px 0;font-size:13px}
.cmd code{display:block;margin-top:2px;padding:6px;background:var(--sf);border-radius:4px;white-space:pre-wrap}
.ids{list-style:none;margin:4px 0;padding:0;font-size:12px;max-height:220px;overflow:auto}
.ids li{padding:2px 0}
.q code,.ids code,.kv code,.cand code,.att code,.cmd code,.rev code{overflow-wrap:anywhere}
.prs{list-style:none;margin:4px 0;padding:0;font-size:13px}
.prs li{padding:4px 0;border-top:1px solid var(--bd)}
.prs li:first-child{border-top:0}
.consts{margin:4px 0;font-size:13px}.const code{color:var(--stale)}
.btn{font:inherit;font-size:13px;height:32px;padding:0 10px;border:1px solid var(--bd);border-radius:var(--r);background:var(--bg);color:var(--ink);cursor:pointer}
.btn:hover{background:var(--sf)}
.copy{display:inline-block;margin:4px 8px 4px 0}
.copy textarea{display:block;width:100%;min-width:280px;height:180px;margin-top:6px;padding:8px;border:1px solid var(--bd);border-radius:var(--r);font:12px var(--mono);color:var(--ink);background:var(--sf)}
.stage{font-size:12px;color:var(--mut);margin-top:2px}
.stage a{color:inherit}
.linksline{display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;font-size:13px;margin:4px 0 8px}
.cols{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin-bottom:8px}
.colh{display:flex;justify-content:space-between;align-items:baseline;gap:4px;font-size:13px;font-weight:600;margin-bottom:4px}
.colh a{text-decoration:none}
.colh .rel{display:inline}
.chip.wide{height:40px;font-size:14px}
.card{border:1px solid var(--bd);border-radius:var(--r);padding:8px;margin:8px 0;font-size:13px}
.card[data-mark="eels-todo"]{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px}
.card[data-mark="eels-todo"]>div{flex-basis:100%}
.tl{list-style:none;margin:0;padding:0;border:1px solid var(--bd);border-radius:var(--r)}
.tli+.tli{border-top:1px solid var(--bd)}
.tlrow,.tli summary{display:grid;grid-template-columns:92px 80px 1fr auto auto;gap:8px;align-items:baseline;padding:8px;font-size:13px}
.tli summary{cursor:pointer;list-style:none}
.tli summary::-webkit-details-marker{display:none}
.tli summary::after{content:"attestation";font-size:12px;color:var(--mut);text-decoration:underline;text-decoration-color:#b9c0c9}
.tli details[open] summary{background:var(--sf)}
.tli .tnote,.tli .consts,.tli .att{margin:0;padding:0 8px 8px;font-size:12px;color:var(--mut)}
.tli .att{padding-top:8px;color:var(--ink)}
.tli.none .ts{color:var(--mut)}
.tw{white-space:nowrap;font-size:12px}
.box>summary{cursor:pointer;margin:24px 0 8px;font-weight:600;font-size:15px}
.split{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:24px}
.todos{list-style:none;margin:0;padding:0;border:1px solid var(--bd);border-radius:var(--r)}
.todo{padding:8px}
.todo+.todo{border-top:1px solid var(--bd)}
.tr1{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}
.rank{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:var(--ink);color:#fff;font-size:12px}
.tr2{margin:4px 0 0 32px;font-size:13px}
.lnk{background:none;border:0;padding:0;font:inherit;color:var(--ink);text-decoration:underline;text-decoration-color:#b9c0c9;text-underline-offset:2px;cursor:pointer}
.runbox{border:1px solid var(--bd);border-radius:var(--r);padding:4px 8px}
.runbox details summary{cursor:pointer}
.sumw{font-size:13px}
.elist{list-style:none;margin:0;padding:0;border:1px solid var(--bd);border-radius:var(--r);max-width:720px}
.erow{display:grid;grid-template-columns:48px 1fr 160px;gap:8px;align-items:center;padding:4px 8px}
.erow+.erow{border-top:1px solid var(--bd)}
.erow .chip{min-width:0}
.q{border:1px solid var(--bd);border-radius:var(--r);padding:8px 12px;margin:8px 0;font-size:13px}
.q .k{font-weight:600}.q .k.bad{color:var(--bad)}.q .k.warn{color:var(--warn)}.q .k.stale{color:var(--stale)}.q .k.none{color:var(--mut)}
.q .act{float:right;margin:0 0 6px 8px;padding:2px 10px;border-radius:999px;background:var(--ink);color:#fff;text-decoration:none;font-size:12px}
.rev{padding:6px 0;border-top:1px solid var(--bd);font-size:13px}
.rev:first-child{border-top:0}
section.start{margin:24px 0}section.start h3{font-size:15px;margin:0 0 4px}
@media (min-width:701px){.scrim{display:none}}
@media (max-width:700px){
body{font-size:15px}
.bar{gap:2px;padding:0 4px;height:52px}
.brand{display:none}
.forks a{display:flex;align-items:center;min-height:44px;padding:0 6px}
.menu{display:inline-flex;align-items:center;height:44px;padding:0 6px;border:1px solid var(--bd);border-radius:var(--r);background:var(--bg);font:inherit;color:var(--ink);order:5}
.qk{display:inline-flex;align-items:center;min-height:44px;padding:0 4px;order:4;color:var(--ink)}
.pnav{display:none;position:absolute;top:52px;left:0;right:0;flex-direction:column;align-items:stretch;background:var(--bg);border-bottom:1px solid var(--bd);padding:8px;gap:0;box-shadow:0 6px 24px rgba(20,23,28,.12)}
.bar.open .pnav{display:flex}
.pnav>a,.pnav>.pop>summary{display:flex;align-items:center;min-height:44px;padding:0 12px}
.pnav>a.on{box-shadow:inset 3px 0 0 var(--ink)}
.pnav .panel{position:static;box-shadow:none;border:0;padding:0 0 0 12px}
.pnav .panel.list a{min-height:44px;align-items:center}
.schip{min-height:44px;padding:0 6px;gap:4px}
.schip .lbl{display:none}
.panel.right{position:fixed;top:56px;left:8px;right:8px;width:auto}
.panel.wide{position:fixed;left:8px;right:8px;top:auto;width:auto}
main{padding:12px 12px 48px}
.find{display:grid;grid-template-columns:auto 1fr;align-items:center;width:100%}
.find label:last-child{grid-column:1/-1}
input[type=search],select{height:44px}
.tools .legend{margin-left:0}
.legend summary{min-height:44px;display:flex;align-items:center}
.tog button{min-height:44px}
table.m:not(.list){min-width:0}
table.m:not(.list) th.row{min-width:150px;max-width:160px}
.tt{white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;font-size:13px}
.chip{height:44px;min-width:84px;font-size:14px}
table.list tr{display:block;margin-bottom:10px}table.list th,table.list td{display:block;width:auto}table.list th.row{width:auto}
#d{top:auto;left:0;right:0;bottom:0;width:auto;max-height:85vh;border-left:0;border-top:1px solid var(--bd);border-radius:12px 12px 0 0;box-shadow:0 -8px 24px rgba(20,23,28,.12)}
.x{width:44px;height:44px}
.dlinks a,.lnk,.linksline a{display:inline-flex;align-items:center;min-height:44px}
.cols{grid-template-columns:repeat(3,minmax(0,1fr))}
.tlrow,.tli summary{grid-template-columns:auto 1fr auto;min-height:44px}
.tlrow .ts,.tli summary .ts{grid-column:1/-1;order:5}
.tli summary::after{display:none}
.split{grid-template-columns:1fr}
.erow{grid-template-columns:44px 1fr 120px;min-height:52px}
.btn{height:44px}
.kv{grid-template-columns:96px 1fr}
.runbox details summary,.box>summary{min-height:44px}
.chip.wide{height:44px}
.q .act{float:none;display:inline-block}
}
@media (prefers-reduced-motion:no-preference){#d{animation:din .14s ease-out}}
@keyframes din{from{transform:translateX(16px);opacity:.6}to{transform:none;opacity:1}}
@media (max-width:700px) and (prefers-reduced-motion:no-preference){#d{animation-name:dup}}
@keyframes dup{from{transform:translateY(24px);opacity:.6}to{transform:none;opacity:1}}
"""

JS = """
let lastFocus=null;
function sel(id){document.querySelectorAll('.sel').forEach(x=>x.classList.remove('sel'));if(id)document.querySelectorAll('[data-open="'+id+'"]').forEach(x=>x.classList.add('sel'))}
function openD(id,el){const t=document.getElementById('t-'+id);if(!t)return false;const c=document.getElementById('c-'+id);if(c&&c.closest('[hidden]')&&document.getElementById('mf'))clearF();
const d=document.getElementById('d');document.getElementById('dc').replaceChildren(t.content.cloneNode(true));d.hidden=false;document.querySelector('.scrim').hidden=false;
lastFocus=el||document.activeElement;sel(id);history.replaceState(null,'','#'+id);d.scrollTop=0;d.querySelector('[data-close]').focus();return true}
function closeD(){const d=document.getElementById('d');if(!d||d.hidden)return;d.hidden=true;document.querySelector('.scrim').hidden=true;sel('');history.replaceState(null,'',location.pathname+location.search);if(lastFocus&&lastFocus.focus)lastFocus.focus()}
function clearF(){document.getElementById('mc').value='';document.getElementById('hp').checked=false;document.getElementById('me').value='';mf()}
function view(v){const on=v==='ac';document.body.classList.toggle('act',on);['st','ac'].forEach(k=>{const b=document.getElementById('v-'+k);if(b)b.setAttribute('aria-pressed',String(k===v))});
const u=new URL(location.href);if(on)u.searchParams.set('view','action');else u.searchParams.delete('view');history.replaceState(null,'',u)}
function own(v){document.querySelectorAll('#queue .q').forEach(q=>q.hidden=!!v&&q.dataset.owner!==v);const u=new URL(location.href);if(v)u.searchParams.set('owner',v);else u.searchParams.delete('owner');history.replaceState(null,'',u)}
addEventListener('click',e=>{const t=e.target;if(!t.closest)return;const o=t.closest('[data-open]');if(o){e.preventDefault();openD(o.dataset.open,o);return}
if(t.closest('[data-close]')||t.classList.contains('scrim')){closeD();return}
document.querySelectorAll('details.pop[open]').forEach(p=>{if(!p.contains(t))p.open=false})});
addEventListener('keydown',e=>{const d=document.getElementById('d');if(e.key==='Tab'&&d&&!d.hidden){const f=[...d.querySelectorAll('a[href],button,summary,[tabindex]')].filter(x=>x.offsetParent),a=f[0],z=f[f.length-1];
if(!d.contains(document.activeElement)){e.preventDefault();a.focus()}else if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}return}
if(e.key!=='Escape')return;const p=document.querySelector('details.pop[open]');if(p){p.open=false;p.querySelector('summary').focus()}else closeD()});
addEventListener('load',()=>{const p=new URLSearchParams(location.search);if(p.get('view')==='action'&&document.getElementById('v-ac'))view('ac');
const o=document.getElementById('own');if(o&&p.get('owner')&&o.querySelector('option[value="'+CSS.escape(p.get('owner'))+'"]')){o.value=p.get('owner');own(o.value)}
const m=document.getElementById('mf');if(m){m.hidden=false;const mc=document.getElementById('mc');if(mc.querySelector('option[value="'+CSS.escape(p.get('client')||'')+'"]'))mc.value=p.get('client')||'';document.getElementById('hp').checked=p.get('hide')==='pass';document.getElementById('me').value=p.get('eip')||'';mf()}
const h=location.hash.slice(1),c=h&&document.getElementById('c-'+h);if(h&&!openD(h,c)&&c)c.scrollIntoView({block:'center'});
const f=document.getElementById('f');if(f&&h.startsWith('eip-')&&f.querySelector('option[value="'+h.slice(4)+'"]')){f.value=h.slice(4);filt(f.value)}
const s=document.getElementById('stale'),t=s&&staleText(s.dataset.taken,Date.now());if(t){s.textContent=t;s.hidden=false}
const g=document.getElementById('age'),k=g&&g.closest('[data-taken]');if(k){g.textContent=ageText(k.dataset.taken,Date.now());if(Date.now()-Date.parse(k.dataset.taken)>216e5)k.classList.replace('ok','old')}
const b=document.querySelector('.bar'),mb=b&&b.querySelector('.menu');if(mb)mb.addEventListener('click',()=>mb.setAttribute('aria-expanded',String(b.classList.toggle('open'))));
document.querySelectorAll('details.pop').forEach(d=>d.addEventListener('toggle',()=>{if(d.open)document.querySelectorAll('details.pop[open]').forEach(x=>{if(x!==d&&!x.contains(d))x.open=false})}))});
function staleText(taken,now){const h=(now-Date.parse(taken))/36e5;return h>6?'data from snapshot '+taken.slice(0,16).replace('T',' ')+' UTC, '+Math.floor(h)+' h old: newer runs or spec changes may exist':''}
function ageText(taken,now){const h=Math.max(0,Math.floor((now-Date.parse(taken))/36e5));return(h<24?h+'h':Math.floor(h/24)+'d '+h%24+'h')+' old'}
function filt(v){document.querySelectorAll('#feed .rev').forEach(r=>r.hidden=!!v&&r.dataset.eip!==v);history.replaceState(null,'',v?'#eip-'+v:location.pathname)}
function mf(){const c=document.getElementById('mc').value,h=document.getElementById('hp').checked,q=document.getElementById('me').value.trim().toLowerCase().replace(/^eip-?/,'');document.querySelectorAll('table.m [data-cl]').forEach(x=>x.hidden=!!c&&x.dataset.cl!==c);document.querySelectorAll('table.m td[data-span]').forEach(x=>x.colSpan=c?1:+x.dataset.span);
document.querySelectorAll('table.m tr[id^="r-"]').forEach(r=>{const t=[...r.querySelectorAll('td.c[data-cl]')].filter(x=>!c||x.dataset.cl===c);r.hidden=(h&&t.length>0&&t.every(x=>x.classList.contains('ok')))||(!!q&&!r.querySelector('th.row').textContent.toLowerCase().includes(q))});
document.getElementById('mf0').hidden=!!document.querySelector('table.m tr[id^="r-"]:not([hidden])');
const u=new URL(location.href);if(c)u.searchParams.set('client',c);else u.searchParams.delete('client');if(h)u.searchParams.set('hide','pass');else u.searchParams.delete('hide');if(q)u.searchParams.set('eip',q);else u.searchParams.delete('eip');history.replaceState(null,'',u)}
function copyMd(b){const t=b.nextElementSibling,l=b.dataset.l||(b.dataset.l=b.textContent),show=()=>{t.hidden=false;t.select()};if(!navigator.clipboard)return show();
navigator.clipboard.writeText(t.value).then(()=>{b.textContent='Copied';setTimeout(()=>{b.textContent=l},1500)},show)}
"""


COUNT_WORD = {"pass": "pass", "open": "untested", "stale-release": "on old tests", "fail": "fails", "no-run": "no run", "no-tests": "no tests"}
COUNT_ORDER = ["fail", "open", "stale-release", "no-tests", "no-run", "pass"]


def eip_href(eip):
    return f"eip-{eip}.html"


def client_href(client):
    return f"client-{client}.html"


def stage_html(info, snap):
    meta = snap.get("meta")
    if not meta:
        return ""
    stage = " / ".join(info.get("stage") or ["not listed"])
    status = f' &middot; EIP status {E(info["status"])}' if info.get("status") else ""
    return f'<div class="stage">{stage_badge(info)}{a(meta["url"], meta["name"])}: {E(stage)}{status}</div>'


def constants_html(delta):
    rows = []
    for c in delta.get("constants", []):
        before = ", ".join(c["before"]) or "none"
        after = ", ".join(c["after"]) or "removed"
        rows.append(f'<div class="const"><code>{E(c["name"])}</code> {E(before)} &rarr; <b>{E(after)}</b></div>')
    return f'<div class="consts" data-mark="constants">{"".join(rows)}</div>' if rows else ""


def eip_name(info):
    if not info.get("test_dir"):
        return info.get("title") or ""
    return info["test_dir"].rsplit("/", 1)[-1].split("_", 1)[1].replace("_", " ")


def tested(snap):
    return [e for e in index.row_order(snap["eips"]) if snap["eips"][e].get("test_dir")]


def untested(snap):
    return [e for e in index.row_order(snap["eips"]) if not snap["eips"][e].get("test_dir")]


def stage_badge(info):
    short = [config.STAGE_SHORT.get(s, s) for s in info.get("stage") or []]
    return "".join(f'<span class="pill sb">{E(s)}</span> ' for s in short)


def no_tests_text(info, snap):
    return f'no EELS tests at {release_short(snap["newest_release"])}: checked {info["checked"]}'


def coverage_html(snap):
    rows = index.row_order(snap["eips"])
    listed = [e for e in rows if set(snap["eips"][e].get("stage") or []) & set(config.TRACKED_STAGES)]
    with_tests = [e for e in listed if snap["eips"][e].get("test_dir")]
    net = [e for e in listed if snap["eips"][e].get("category") == "Networking"]
    line = f'SFI+CFI in {E(snap["meta"]["name"])}: {len(listed)} EIPs, {len(with_tests)} with EELS tests, {len(listed) - len(with_tests)} without'
    if net:
        line += f' &middot; Networking EIPs ({", ".join("EIP-" + e for e in net)}) are out of EELS scope'
    return f'<span class="fact" data-mark="coverage">{line}</span>'


def headline_counts(cells):
    counts = {}
    for c in cells:
        counts[c["headline"]] = counts.get(c["headline"], 0) + 1
    return [(h, counts[h]) for h in COUNT_ORDER if h in counts]


def counts_html(cells):
    return " &middot; ".join(f'<span class="hl {STATE_CLASS[h]}">{n} {E(COUNT_WORD[h])}</span>' for h, n in headline_counts(cells))


def counts_text(cells):
    return " · ".join(f"{n} {COUNT_WORD[h]}" for h, n in headline_counts(cells))


def counts_glyph(cells, words=False):
    return " ".join(f'<span class="cnt {STATE_CLASS[h]}">{glyph(STATE_CLASS[h])}<span class="n">{n}</span>'
                    + (f" {E(COUNT_WORD[h])}" if words else f'<span class="sr"> {E(COUNT_WORD[h])}</span>') + "</span>" for h, n in headline_counts(cells))


def attestation_for(eip, commit, attestations):
    mine = [a for a in attestations if a["eip"] == eip and commit.startswith(str(a["commit"]))]
    return mine[-1] if mine else None


def delta_word(eip, commit, attestations):
    at = attestation_for(eip, commit, attestations)
    if not at:
        return "open"
    if at.get("kind") == "editorial":
        return "editorial"
    if "killed" not in at:
        return "open"
    return "covered" if at["killed"] else "mutant-survived"


def rev_state(eip, info, rev, attestations):
    if any(d["commit"] == rev["commit"] for d in info["deltas"]):
        st = delta_word(eip, rev["commit"], attestations)
        return st, LABEL[st]
    if not info.get("pin"):
        return "n/a", "no EELS tests"
    if rev["commit"] == info["pin"]["commit"]:
        return "pass", f'EELS {release_short(info["pin"]["release"])} implements this text'
    return "n/a", "older"


def tests_info(rev, info, snap):
    if info.get("pin_history") is None:
        return None
    t = index.rev_tests(rev, info, snap.get("runs") or {})
    m = t["move"]
    out = {"state": t["state"], "ran": t["ran"], "release": t["release"], "eels_commit": None, "eels_pr": None, "eels_url": None, "files": []}
    if m:
        out.update({"eels_commit": m["commit"], "eels_pr": m["pr"], "eels_date": m["date"], "files": m["files"],
                    "eels_url": gh(config.EELS_REPO, "pull", m["pr"]) if m["pr"] else gh(config.EELS_REPO, "commit", m["commit"])})
    return out


def files_text(files):
    shown = [f for f in files if f.startswith("test_")][:3]
    rest = len([f for f in files if f.startswith("test_")]) - len(shown)
    return ", ".join(shown) + (f" and {rest} more" if rest > 0 else "")


def pinned_text(info):
    pin = info["pin"]
    if not pin["commit"]:
        return f'a text that is not in the EIP history (pin {E(pin.get("version", pin["blob"])[:8])})'
    date = next((r["date"][:10] for r in info["revisions"] if r["commit"] == pin["commit"]), None)
    link = f'<code>{a(gh(config.EIPS_REPO, "commit", pin["commit"]), pin["commit"][:8])}</code>'
    return f'the text from {E(date)} ({link})' if date else f'the text of EIP commit {link}'


def eels_item(eip, snap):
    return eels_todo(eip, snap["eips"][eip], snap["newest_release"], config.GITHUB, config.EIPS_REPO)


def eels_detail(todo, snap):
    if todo["kind"] == "no-tests":
        return no_tests_text(snap["eips"][todo["eip"]], snap) + "."
    consts = "; ".join(f'{c["name"]} {", ".join(c["before"]) or "none"} -> {", ".join(c["after"]) or "removed"}' for c in todo["constants"])
    since = f'EIP commit {todo["pin_commit"][:8]}' if todo["pin_commit"] else "a text not in the EIP history"
    return (f'EELS {release_short(todo["pin_release"])} tests {since}; the EIP changed {plural(todo["behind"], "time")} since, '
            f'newest {todo["head"][:8]} on {todo["head_date"][:10]}.' + (f" Named constants: {consts}." if consts else ""))


def eels_todo_html(todo, snap):
    if not todo:
        return ""
    link = f' {a(todo["diff_url"], "EIP diff")}' if todo.get("diff_url") else ""
    consts = "".join(f'<div class="const"><code>{E(c["name"])}</code> {E(", ".join(c["before"]) or "none")} &rarr; <b>{E(", ".join(c["after"]) or "removed")}</b></div>'
                     for c in todo.get("constants", []))
    return (f'<div class="card" data-mark="eels-todo">{chip("stale", "EELS to do")} <b>{E(todo["action"])}</b>{link}'
            f'<div class="muted">{E(eels_detail(todo, snap))}</div>' + (f'<div class="consts">{consts}</div>' if consts else "") + '</div>')


def rev_note(eip, rev, info):
    out = ""
    named = index.subject_eips(rev["subject"])
    if named and eip not in named:
        out += f' <span class="muted" data-mark="other-eip">(commit for {E(", ".join("EIP-" + n for n in sorted(named, key=int)))}; it also edits this EIP)</span>'
    delta = next((d for d in info.get("deltas") or [] if d["commit"] == rev["commit"]), None)
    if delta and index.header_only(delta.get("diff", "")):
        out += ' <span class="pill none" data-mark="header-only">header only</span>'
    return out


def tests_line(rev, info, snap):
    t = tests_info(rev, info, snap)
    if t is None:
        return ""
    if t["state"] == "waiting":
        return (f'<div class="tnote" data-mark="not-updated"><b>tests:</b> not updated to this text. EELS {E(release_short(info["pin"]["release"]))} '
                f'still tests {pinned_text(info)}.</div>')
    if t["state"] == "never":
        return '<div class="tnote"><b>tests:</b> no EELS release tests this text.</div>'
    if t["eels_url"]:
        who = f'EELS PR #{t["eels_pr"]}' if t["eels_pr"] else f'EELS commit {t["eels_commit"][:8]}'
        files = files_text(t["files"])
        parts = [f'<b>tests:</b> {a(t["eels_url"], who)} pinned this text on {E(t["eels_date"][:10])}'
                 + (f', test files {E(files)}' if files else "")]
    else:
        parts = ["<b>tests:</b> an EELS release pins this text"]
    if t["state"] == "unreleased":
        parts.append("not in a release yet")
    elif t["state"] == "superseded":
        parts.append("a later EELS pin replaced it before any release, so no client ran it")
    else:
        rel = t["release"]
        parts.append(f'first release {a(gh(config.EELS_REPO, "releases/tag", rel.replace("@", "%40")), release_short(rel))}')
        runs = snap.get("runs") or {}
        parts.append("run against it: " + ", ".join(a(runs[c]["url"], config.CLIENT_LABEL[c]) for c in t["ran"]) if t["ran"]
                     else "no client run on a release with this text")
    return '<div class="tnote">' + " &middot; ".join(parts) + "</div>"


def pending_html(rows):
    return '<ul class="prs">' + "".join(f'<li>{a(p["url"], p["repo"].split("/")[1] + "#" + str(p["number"]))} {E(p["title"])}</li>' for p in rows) + "</ul>"


PR_STATE = {"open": "warn", "merged": "ok"}


def merged_since(snap, key="linked_prs"):
    return next((b["merged_since"] for b in (snap.get(key) or {}).values() if b.get("merged_since")), f"the last {handoff.MERGED_DAYS} days")


def client_prs_html(snap, eip):
    rows = []
    for client in config.CLIENTS:
        c = handoff.client_prs(snap, client, eip)
        if c["state"] == "unreachable":
            body = '<em>lookup failed in this snapshot</em>'
        elif c["state"] == "not-collected":
            body = '<em>not collected in this snapshot</em>'
        elif not c["prs"]:
            body = '<em>none found by title</em>'
        else:
            body = " ".join(f'{a(p["url"], "#" + str(p["number"]))} <span class="pill {PR_STATE.get(p["state"], "none")}">{E(p["state"])}</span> {E(p["title"])}<br>'
                            for p in c["prs"]) + ('<em>PR list hit its page limit; more PRs may exist</em>' if c.get("truncated") else "")
        rows.append(f'<tr><th class="row">{a(f"{config.GITHUB}/{c["repo"]}/pulls", config.CLIENT_LABEL[client])}</th><td class="prs">{body}</td></tr>')
    return "".join(rows)


def code_pr_line(p):
    word = "not on default branch" if p["state"] == "merged-elsewhere" else p["state"]
    return f'{a(p["url"], "#" + str(p["number"]))} <span class="pill {PR_STATE.get(p["state"], "none")}" title="{E(p["title"])}">{E(word)}</span>'


def code_html(snap, eip, attestations):
    rows = []
    for c in codepr.cells(snap, eip, attestations):
        pill = (f'<span class="pill {codepr.PILL[c["status"]]}" data-mark="code-{c["status"]}">{E(codepr.WORD[c["status"]])}</span>' if c["state"] == "ok"
                else '<span class="pill none">-</span>')
        files = f' title="{E(", ".join(c["paths"]))}"' if c.get("paths") else ""
        prs = " ".join(code_pr_line(p) for p in c.get("prs", [])[:3]) + (f' <em>+{len(c["prs"]) - 3} more</em>' if len(c.get("prs", [])) > 3 else "")
        rows.append(f'<tr><th class="row">{a(f"{config.GITHUB}/{c["repo"]}", c["label"])} <small>{E(config.CODE_CLIENTS[c["client"]]["layer"].upper())}</small></th>'
                    f'<td class="prs">{pill} <span class="muted"{files}>{E(codepr.evidence_text(c))}</span> {prs}</td></tr>')
    return ''.join(rows)


def linked_html(eip, snap, attestations=()):
    pend = handoff.pending_spec(snap, eip)
    spec = (f'<details class="box" data-mark="pending-prs"><summary>Open EIP PRs <span class="num">{len(pend)}</span> <span class="muted small">not merged, not counted</span></summary>'
            f'<p class="muted">open PRs in EIPs and execution-specs that name this EIP; shown for reference, they never change a verdict</p>{pending_html(pend)}</details>' if pend else "")
    if snap.get("code_status") is not None:
        return (spec + f'<h2>Code and PRs</h2><p class="muted">code merged: at least {codepr.MIN_CODE_FILES} files on the default branch name EIP-{eip} in path or contents, '
                f'or a merged PR whose title names it; spec changed since: a spec change after the last merged PR; '
                f'PRs merged since {E(merged_since(snap, "code_status"))}; a hint from names, it never changes a test verdict</p>'
                f'<div class="wrap"><table class="m list" data-mark="code-status">{code_html(snap, eip, attestations)}</table></div>')
    return (spec
            + f'<details class="box" data-mark="client-prs-box"><summary>Client PRs <span class="muted small">matched by title, not a verdict</span></summary>'
            f'<p class="muted">open and merged PRs whose title names EIP-{eip}; merged ones since {E(merged_since(snap))}</p>'
            f'<div class="wrap"><table class="m list" data-mark="client-prs">{client_prs_html(snap, eip)}</table></div></details>')


def timeline_html(eip, info, snap, attestations):
    deltas = {d["commit"]: d for d in info.get("deltas") or []}
    items = []
    for rev in reversed(info["revisions"]):
        st, word = rev_state(eip, info, rev, attestations)
        k = STATE_CLASS[st]
        row = (f'<span class="td mono">{E(rev["date"][:10])}</span><code>{a(gh(config.EIPS_REPO, "commit", rev["commit"]), rev["commit"][:8])}</code>'
               f'<span class="ts">{E(rev["subject"])}{rev_note(eip, rev, info)}</span><span class="tw {k}">{glyph(k)} {E(word)}</span>')
        extra = tests_line(rev, info, snap) + (constants_html(deltas[rev["commit"]]) if rev["commit"] in deltas else "")
        proof = proof_html(attestation_for(eip, rev["commit"], attestations)) if rev["commit"] in deltas else ""
        if proof:
            items.append(f'<li class="tli {k}"><details><summary>{row}</summary>{extra}{proof}</details></li>')
        else:
            items.append(f'<li class="tli {k}"><div class="tlrow">{row}</div>{extra}</li>')
    return f'<ol class="tl" data-mark="spec-tests">{"".join(items)}</ol>'


def eip_head(eip, info, snap, json_href, links):
    return (f'<div class="crumbs"><a href="index.html">Status</a> / EIP-{E(eip)}</div>'
            + titlebar(f'EIP-{E(eip)} <span class="muted">{E(info.get("title") or eip_name(info))}</span>', stage_html(info, snap), json_href)
            + f'<div class="linksline">{" &middot; ".join(links)}</div>')


def eip_text_link(info):
    return a(f"{config.GITHUB}/{config.EIPS_REPO}/blob/{config.EIPS_BRANCH}/{info['path']}", "EIP text")


def untested_page_html(eip, snap, attestations):
    info = snap["eips"][eip]
    return (eip_head(eip, info, snap, "api/eips.json", [eip_text_link(info), a_local(f"changes.html#eip-{eip}", "all spec changes")])
            + f'<div class="card" data-mark="no-tests"><b>no tests yet</b> <span class="muted">{E(no_tests_text(info, snap))}. '
            f'No client cell is shown: there is nothing to run.</span></div>{eels_todo_html(eels_item(eip, snap), snap)}'
            f'<h2>Spec changes <span class="muted small">newest first</span></h2>{timeline_html(eip, info, snap, attestations)}{linked_html(eip, snap, attestations)}')


def release_label(release, newest):
    old = bool(release) and release != newest
    return (f'<span class="rel{" oldrel" if old else ""}">{glyph("stale") if old else ""}{E(release_short(release) if release else "-")}'
            + ('<span class="sr"> old release</span>' if old else "") + "</span>")


def cell_button(cell, extra="", action=""):
    k = STATE_CLASS[cell["headline"]]
    cid = f'{cell["eip"]}-{cell["client"]}'
    return (f'<button type="button" class="chip {k}{extra}" data-open="{cid}"><span class="st">{glyph(k)}<span class="n">{E(run_count(cell))}</span>'
            f'<span class="sr"> EIP-{cell["eip"]} {E(config.CLIENT_LABEL[cell["client"]])}: {E(headline_text(cell))}</span></span>{action}</button>')


def cell_templates(cells, snap):
    return "".join(f'<template id="t-{c["eip"]}-{c["client"]}">{drawer(c, snap)}</template>' for c in cells)


def eip_page_html(eip, snap, cells, attestations):
    info = snap["eips"][eip]
    if not info.get("test_dir"):
        return untested_page_html(eip, snap, attestations)
    mine = [c for c in cells if c["eip"] == eip]
    newest = snap["newest_release"]
    cols = "".join(f'<div class="col"><div class="colh">{a_local(client_href(c["client"]), config.CLIENT_LABEL[c["client"]])}'
                   f'{release_label(c["links"]["run"].get("release"), newest)}</div>{cell_button(c, " wide")}</div>' for c in mine)
    cols += f'<div class="col"><div class="colh">EELS<span class="rel">tests {E(release_short(newest))}</span></div>{eels_button(eip, info, mine, snap, " wide")}</div>'
    links = [eip_text_link(info), a(test_dir_url(info["pin"]["release"], info["test_dir"]), "EELS tests"),
             a_local(f"changes.html#eip-{eip}", "all spec changes"), copy_md(eip_markdown(eip, snap, cells, attestations))]
    return (eip_head(eip, info, snap, f"api/eip/{eip}.json", links)
            + f'<h2>Clients <span class="muted small">open a cell for the why, the three checks and the evidence</span></h2><div class="cols">{cols}</div>'
            f'{eels_todo_html(eels_item(eip, snap), snap)}'
            f'<h2>Spec changes and their tests <span class="muted small">newest first; each EIP commit, the EELS change that pinned it, its first release and the client runs on it</span></h2>'
            f'{timeline_html(eip, info, snap, attestations)}{linked_html(eip, snap, attestations)}'
            + cell_templates(mine, snap) + f'<template id="t-{eip}-{EELS}">{eels_drawer(eip, info, mine, snap)}</template>')


def client_prs_section(snap, client, eips):
    found = [handoff.client_prs(snap, client, e) for e in eips] or [handoff.client_prs(snap, client, "")]
    repo = found[0]["repo"]
    prs = list({p["number"]: p for f in found for p in f["prs"]}.values())
    state = {"not-collected": "not collected in this snapshot", "unreachable": "lookup failed in this snapshot"}.get(found[0]["state"])
    rows = "".join(f'<li>{a(p["url"], "#" + str(p["number"]))} <span class="pill {PR_STATE.get(p["state"], "none")}">{E(p["state"])}</span> {E(p["title"])}</li>' for p in prs)
    line = state or (f'{plural(len(prs), "PR")} whose title names a tracked EIP' if prs else "none found by title")
    return f'<h2>Client PRs</h2><p class="muted">{a(f"{config.GITHUB}/{repo}/pulls", repo)}: {line}</p>' + (f'<ul class="prs">{rows}</ul>' if rows else "")


def client_page_html(client, snap, cells, items):
    label = config.CLIENT_LABEL[client]
    mine = [c for c in cells if c["client"] == client]
    run = snap["runs"].get(client)
    if run:
        wide = run["client_wide_failures"]
        stale = (f' <span class="pill stale">newest is {E(release_short(snap["newest_release"]))}</span>'
                 if run["release"] != snap["newest_release"] else "")
        other = (f'<details><summary><span class="num">{len(wide)}</span> {"failing case" if len(wide) == 1 else "failing cases"} in tests for EIPs this site does not track, not counted above</summary>{ids_list(wide)}</details>'
                 if wide else "no failing cases in tests for EIPs this site does not track")
        receipt = ('<div class="runbox">' + kv("tests", f'<code>{E(run["release"])}</code>{stale}')
                   + kv("image", f'<code>{E(run["image"] or "?")}</code>') + kv("version", f'<code>{E(run["version"])}</code>')
                   + kv("run", f'{E(run["start"][:16].replace("T", " "))}Z &rarr; {a(run["url"], "hive run")} &middot; {a(run["sim_log"], "sim log")}')
                   + kv("cases", f'<span class="num">{run["ntests"] - run["fails"]}/{run["ntests"]}</span> pass in the whole run')
                   + kv("other tests", other) + '</div>')
    else:
        receipt = f'<div class="runbox muted">No {E(config.SIMULATOR)} run for {E(label)}.</div>'
    todo = []
    for i, it in enumerate([it for it in items if client in it["clients"]], 1):
        k = STATE_CLASS[QUEUE_STATE[it["kind"]]]
        evidence = f'<button type="button" class="lnk" data-open="{it["eip"]}-{client}">evidence</button>'
        detail = (f'<span class="muted">{plural(len(it["failed"]), "failing case")}</span>{ids_list(it["failed"])}' if it["kind"] == "run-fail"
                  else queue_detail(it, snap))
        todo.append(f'<li class="todo"><div class="tr1"><span class="rank num">{i}</span><b>{E(it["action"])}</b>{a_local(eip_href(it["eip"]), "EIP-" + it["eip"])}'
                    f'{chip(k, QUEUE_WORD[it["kind"]])}{evidence}</div><div class="tr2">{detail}</div></li>')
    todo_html = f'<ol class="todos">{"".join(todo)}</ol>' if todo else '<p class="muted">Nothing to do: every tracked EIP passes on the newest tests.</p>'
    rows = "".join(f'<li class="erow"><a class="eipn" href="{eip_href(c["eip"])}">{c["eip"]}</a><span class="tt">{E(snap["eips"][c["eip"]].get("title") or eip_name(snap["eips"][c["eip"]]))}</span>'
                   f'{cell_button(c, " wide")}</li>' for c in mine)
    repo = config.CLIENT_REPO[client]
    return (f'<div class="crumbs"><a href="index.html">Status</a> / {E(label)}</div>'
            + titlebar(E(label), f'<span class="sumw">{counts_glyph(mine, True)}</span>{a(f"{config.GITHUB}/{repo}", repo, "mono")}', f"api/client/{client}.json")
            + f'<div class="split"><section><h2>To do <span class="muted small">most important first</span></h2>{todo_html}</section>'
            f'<section><h2>Run</h2>{receipt}</section></div>'
            f'<section><h2>EIPs <span class="muted small">open a cell for the why and the evidence</span></h2>{legend_html()}<ul class="elist">{rows}</ul></section>'
            + client_prs_section(snap, client, [c["eip"] for c in mine]) + cell_templates(mine, snap))


QUEUE_STATE = {"run-fail": "fail", "open-delta": "open", "stale-release": "stale-release", "run-missing": "no-run"}
MISSING_WORD = {"no-run": "no run", "no-tests": "no tests in run"}
QUEUE_WORD = {"run-fail": "fails", "open-delta": "spec change untested", "stale-release": "old tests", "run-missing": "not run on newest tests"}


def queue_detail(it, snap):
    if it["kind"] == "run-fail":
        return f'{len(it["failed"])} failing: ' + ", ".join(f"<code>{E(short_test(f))}</code>" for f in it["failed"][:3])
    if it["kind"] == "open-delta":
        delta = next(d for d in snap["eips"][it["eip"]]["deltas"] if d["commit"] == it["commit"])
        return E(f'{it["commit"][:8]} {delta["subject"]}')
    if it["kind"] == "run-missing":
        return E(f'{MISSING_WORD[it["headline"]]} at {release_short(snap["newest_release"])}')
    return E(f'last ran {release_short(it["release"])}')


def a_local(href, text):
    return f'<a href="{E(href)}">{E(text)}</a>'


def feed_rows(snap, attestations):
    rows = []
    for eip in index.row_order(snap["eips"]):
        info = snap["eips"][eip]
        for rev in info["revisions"]:
            st, word = rev_state(eip, info, rev, attestations)
            rows.append({"eip": eip, "commit": rev["commit"], "date": rev["date"], "subject": rev["subject"], "state": st, "word": word,
                         "url": gh(config.EIPS_REPO, "commit", rev["commit"]), "tests": tests_info(rev, info, snap) if info.get("pin") else None})
    return sorted(rows, key=lambda r: (datetime.fromisoformat(r["date"]), r["eip"], r["commit"]), reverse=True)


def feed_tests(t):
    if not t or t["state"] == "never":
        return ""
    if t["state"] == "waiting":
        return ' <span class="muted">&middot; tests not updated yet</span>'
    rel = f' in {E(release_short(t["release"]))}' if t["release"] else " replaced before release" if t["state"] == "superseded" else " unreleased"
    if not t["eels_url"]:
        return f' <span class="muted">&middot; tests: EELS{rel}</span>'
    who = f'EELS #{t["eels_pr"]}' if t["eels_pr"] else f'EELS {t["eels_commit"][:8]}'
    return f' <span class="muted">&middot; tests: {a(t["eels_url"], who)}{rel}</span>'


def feed_html(snap, rows, pending=()):
    eips = index.row_order(snap["eips"])
    opts = '<option value="">all EIPs</option>' + "".join(
        f'<option value="{e}">EIP-{e} ({sum(r["eip"] == e for r in rows)})</option>' for e in eips)
    items = "".join(f'<div class="rev" data-eip="{r["eip"]}">{a_local(eip_href(r["eip"]), "EIP-" + r["eip"])} '
                    f'<code>{a(r["url"], r["commit"][:8])}</code> <span class="muted">{E(r["date"][:10])}</span> {E(r["subject"])} '
                    f'<span class="pill {STATE_CLASS[r["state"]]}">{E(r["word"])}</span>{feed_tests(r["tests"])}</div>' for r in rows)
    return (titlebar("Spec changes", '<span class="muted">every change to a tracked EIP text, newest first</span>', "api/changes.json")
            + f'<p class="muted">proven: a spec with the change undone fails a test, and EELS has that test &middot; untested: no proof yet '
            f'&middot; wording only: no behaviour &middot; older: EELS already implements a later text</p>'
            f'<p><label for="f">Show</label> <select id="f" onchange="filt(this.value)">{opts}</select></p>'
            f'<div class="card" id="feed">{items}</div>'
            + (f'<h2>Open spec PRs <span class="muted small">not merged, not counted</span></h2><div class="card">{pending_html(pending)}</div>' if pending else ""))


def stale_banner(snap):
    if snap.get("source") in ("archive", "snapshot"):
        return ""
    return f'<p class="stale" id="stale" role="status" hidden data-taken="{E(snap["taken_at"])}"></p>'


def fallback_banner(snap):
    if snap.get("source") != "snapshot":
        return ""
    return (f'<div class="strip" id="fallback" role="alert">data from snapshot {E(snap["taken_at"][:10])}: '
            f'the live rebuild did not run, so this page may be out of date</div>')


def fork_href(fork, root=""):
    up = root + ("../" if config.SUBDIR else "")
    sub = config.FORKS[fork]["SUBDIR"]
    return up + (f"{sub}/" if sub else "") + "index.html"


def forks_nav(root=""):
    links = "".join(f'<a href="{fork_href(f, root)}" class="{"on" if f == config.FORK else ""}">{E(v["FORK_LABEL"])}</a>' for f, v in config.FORKS.items())
    return f'<nav class="forks" aria-label="Fork">{links}</nav>'


def archived_banner(snap):
    if snap.get("source") != "archive":
        return ""
    return (f'<div class="strip age" id="archived" role="status">archived snapshot {E(snap["taken_at"])}, shown with the current code and proofs '
            f'&middot; <a href="../../index.html">latest data</a> &middot; <a href="../../history.html">all snapshots</a></div>')


def asof_href(snap):
    if snap.get("source") == "archive":
        return "index.html"
    return snap.get("asof") or build.permalink(snap["taken_at"])


def scoped(body):
    return re.sub(r'<th\b(?![^>]*scope=)([^>]*)>', lambda m: f'<th{m.group(1)} scope="{"row" if "class=\"row" in m.group(1) else "col"}">', body)


NAV = [("matrix", "index.html", "Status")]
NAV_AFTER = [("changes", "changes.html", "Changes"), ("queue", "queue.html", "Queue")]
MORE = [("start", "start.html", "Start here"), ("releases", "releases.html", "Test releases"), ("divergences", "divergences.html", "Divergences"), ("prs", "prs.html", "PRs"), ("history", "history.html", "History")]


def nav_links(rows, nav, root=""):
    return "".join(f'<a href="{root if key == "history" else ""}{href}" class="{"on" if key == nav else ""}"{" aria-current=page" if key == nav else ""}>{E(label)}</a>'
                   for key, href, label in rows)


def clients_nav(snap):
    return ('<details class="pop clients"><summary>My client</summary><div class="panel list">'
            + "".join(f'<a href="{client_href(c)}">{E(config.CLIENT_LABEL[c])}<span class="muted mono">{E(release_short(snap["runs"][c]["release"]) if c in snap["runs"] else "no run")}</span></a>'
                      for c in config.CLIENTS) + "</div></details>")


def snapshot_chip(snap):
    old = snap.get("source") in ("archive", "snapshot")
    return (f'<details class="pop snap"><summary class="schip {"old" if old else "ok"}" data-taken="{E(snap["taken_at"])}">{glyph("stale")}'
            f'<span><span class="lbl">Snapshot </span><span id="age">{E(snap["taken_at"][:10])}</span></span><span class="sr">, open for snapshot details</span></summary>'
            f'<div class="panel right"><p class="asof">as of <a href="{E(asof_href(snap))}" title="permalink to this snapshot">{E(snap["taken_at"])}</a></p>'
            + kv("fork", f'{E(config.FORKS[config.FORK]["FORK_LABEL"])} &middot; EL')
            + kv("newest EELS", a(snap["release_url"], snap["newest_release"]))
            + kv("hive", f'{a(snap["listing_url"], "hive listing")} <span class="num">{snap["listing_rows"]}</span> runs') + f"{stale_banner(snap)}</div></details>")


def header_html(nav, snap, root):
    return (f'<header class="bar"><a class="brand" href="index.html">{E(config.NAME)}</a>{forks_nav(root)}<a class="qk" href="queue.html">Queue</a>'
            f'<button type="button" class="menu" aria-expanded="false" aria-controls="pnav">Menu</button>'
            f'<nav class="pnav" id="pnav" aria-label="Primary">{nav_links(NAV, nav)}{clients_nav(snap)}{nav_links(NAV_AFTER, nav)}'
            f'<details class="pop more"><summary>More</summary><div class="panel list">{nav_links(MORE, nav, root)}</div></details></nav>'
            f'{snapshot_chip(snap)}</header>')


def page(title, nav, body, snap):
    root = "../../" if snap.get("source") == "archive" else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(title)}</title><style>{CSS}</style></head><body>'
            f'{header_html(nav, snap, root)}<main>{fallback_banner(snap)}{archived_banner(snap)}{scoped(body)}</main>'
            f'<div class="scrim" hidden></div><aside id="d" role="dialog" aria-modal="true" aria-label="Evidence" hidden><div id="dc"></div></aside><script>{JS}</script></body></html>')


def cells_for(snap, attestations):
    cells = []
    for eip in tested(snap):
        for client in config.CLIENTS:
            cell = chain(eip, client, snap, attestations)
            cell["links"]["_dir"] = snap["eips"][eip]["test_dir"].rsplit("/", 1)[-1]
            cells.append(cell)
    return cells


def legend_html():
    items = [("ok", "pass"), ("bad", "fails"), ("stale", "old tests, re-run"), ("warn", "spec change untested"), ("none", "no data")]
    return ('<div class="legend">' + "".join(f'<span class="lg {k}">{glyph(k)} {E(w)}</span>' for k, w in items)
            + '<details class="pop how"><summary>How to read</summary><div class="panel wide">'
            '<p>Each cell shows its weakest check. Numbers are tests passed / total for the EIP\'s test directory on the release the client ran. '
            'Open a cell for the three checks: <b>spec change</b> &middot; <b>test proof</b> &middot; <b>client run</b>.</p>'
            '<p><span class="pill sb">SFI</span> Scheduled for inclusion &middot; <span class="pill sb">CFI</span> Considered for inclusion.</p>'
            '<p><span class="nb d">&Delta; 1</span> spec changes since the version EELS implements &middot; <span class="nb p">PR 11</span> open EIP PRs, not merged, not counted.</p>'
            f'<p>Column headers show the test release each client ran; {glyph("stale")} marks a release older than the newest EELS release.</p></div></details></div>')


def row_head(eip, info):
    nb = ""
    if info.get("deltas"):
        nb += (f'<span class="nb d" title="EIP text changed after the version EELS implements"><span aria-hidden="true">&Delta;</span> '
               f'<span class="num">{len(info["deltas"])}</span><span class="sr"> spec changes since EELS</span></span>')
    if info.get("pending"):
        nb += f'<span class="nb p" title="open EIP PRs, not spec yet">PR <span class="num">{len(info["pending"])}</span><span class="sr"> open EIP PRs, not counted</span></span>'
    stage = "".join(f'<span class="{k}">{E(x)}</span>' for k, x in (("st", " · ".join(info.get("stage") or [])), ("es", info.get("status"))) if x)
    return (f'<th class="row"><a href="{eip_href(eip)}" class="eipn">{E(eip)}</a> <span class="tt">{E(info.get("title") or eip_name(info))}</span>'
            f'<div class="r2">{stage_badge(info)}{stage}{nb}</div></th>')


def matrix_html(snap, cells):
    by = {(c["eip"], c["client"]): c for c in cells}
    newest = snap["newest_release"]
    head = ('<thead><tr><th class="corner">EIP</th>'
            + "".join(f'<th class="ch" data-cl="{c}">{a_local(client_href(c), config.CLIENT_LABEL[c])}{release_label(snap["runs"][c]["release"] if c in snap["runs"] else None, newest)}</th>' for c in config.CLIENTS)
            + f'<th class="ch eels">{a(gh(config.EELS_REPO, "releases/tag", newest.replace("@", "%40")), "EELS")}<span class="rel">tests {E(release_short(newest))}</span></th></tr>')
    head += ('<tr class="sums"><th class="row">by weakest check</th>'
             + "".join(f'<td class="sum" data-cl="{cl}" title="{E(counts_text(mine))}">{counts_glyph(mine)}</td>'
                       for cl, mine in ((cl, [c for c in cells if c["client"] == cl]) for cl in config.CLIENTS)) + '<td class="sum"></td></tr></thead>')
    rows, templates = [], []
    for eip in index.row_order(snap["eips"]):
        info = snap["eips"][eip]
        mine = [by[(eip, cl)] for cl in config.CLIENTS if (eip, cl) in by]
        templates.append(f'<template id="t-{eip}-{EELS}">{eels_drawer(eip, info, mine, snap)}</template>')
        if not info.get("test_dir"):
            rows.append(f'<tr class="nt" id="r-{eip}">{row_head(eip, info)}'
                        f'<td class="c none" colspan="{len(config.CLIENTS)}" data-span="{len(config.CLIENTS)}" data-mark="no-tests"><div class="st"><div class="hl">no tests yet</div><div class="sub">{E(no_tests_text(info, snap))}</div></div>'
                        f'{action_html(None, "")}</td>{eels_cell(eip, info, [], snap)}</tr>')
            continue
        tds = "".join(f'<td class="c {STATE_CLASS[c["headline"]]}" id="c-{c["eip"]}-{c["client"]}" data-cl="{c["client"]}">'
                      f'{cell_button(c, "", action_html(cell_action(c, newest), config.CLIENT_LABEL[c["client"]]))}</td>' for c in mine)
        templates.append(cell_templates(mine, snap))
        rows.append(f'<tr id="r-{eip}">{row_head(eip, info)}{tds}{eels_cell(eip, info, mine, snap)}</tr>')
    wide = {c: r["client_wide_failures"] for c, r in snap["runs"].items() if r["client_wide_failures"] and r["release"] == newest}
    facts = coverage_html(snap) if snap.get("meta") else ""
    if wide:
        facts += ('<span class="fact">Failing cases in untracked EIP tests, not counted: <span class="uts">' + " ".join(
            f'<a class="ut" href="{client_href(c)}">{E(config.CLIENT_LABEL[c])} <span class="num">{len(v)}</span></a>' for c, v in wide.items()) + "</span></span>")
    toggle = ('<div class="tog" role="group" aria-label="Cell view"><button type="button" id="v-st" aria-pressed="true" onclick="view(\'st\')">Status</button>'
              '<button type="button" id="v-ac" aria-pressed="false" onclick="view(\'ac\')">Next action</button></div>')
    find = ('<div class="find" id="mf" hidden><label for="me">EIP</label> <input type="search" id="me" placeholder="number or name" autocomplete="off" oninput="mf()"> <label for="mc">Client</label> <select id="mc" onchange="mf()"><option value="">All clients</option>'
            + "".join(f'<option value="{c}">{E(config.CLIENT_LABEL[c])}</option>' for c in config.CLIENTS)
            + '</select> <label><input type="checkbox" id="hp" onchange="mf()"> Hide passing rows</label></div>')
    sub = " &middot; ".join(E(x) for x in (config.FORKS[config.FORK]["FORK_LABEL"], (snap.get("meta") or {}).get("name")) if x)
    return (titlebar("EIP status by client", f'<span class="muted">{sub}</span>', "api/eips.json")
            + f'<div class="facts">{facts}</div><div class="tools">{toggle}{find}{legend_html()}</div>'
            + f'<div class="wrap" tabindex="0" aria-label="Status grid, scrolls sideways"><table class="m" id="grid">{head}<tbody>{"".join(rows)}</tbody></table></div>'
            + '<p class="muted" id="mf0" hidden>No rows match. Clear the EIP search or "Hide passing rows".</p>' + "".join(templates))


def action_html(verb, owner):
    if verb is None:
        return '<div class="ac" data-mark="act"><div class="hl none">nothing to do</div></div>'
    return f'<div class="ac" data-mark="act"><div class="hl av">{E(verb)}</div><div class="sub">owner: {E(owner)}</div></div>'


def eels_state(info, cells, snap):
    if not info.get("test_dir"):
        return "none", "no tests", "no tests", f"no test dir at {release_short(snap['newest_release'])}"
    behind = len(info["deltas"])
    untested_n = len(delta_verbs(cells))
    if untested_n:
        return "warn", f"{untested_n} untested", f"{plural(untested_n, 'spec change')} untested", f"{behind} since the EELS pin"
    if behind and not any(c["links"]["test"]["deltas"] for c in cells):
        return "none", "not checked", "spec changes not checked", f"{behind} since the EELS pin, no run on the newest tests"
    if behind:
        return "ok", "proven", "spec changes proven", f"{behind} since the EELS pin"
    return "ok", "current", "implements current text", f"pin {info['pin']['blob'][:8]}"


def eels_next(eip, info, cells, snap):
    verb, n = eels_action(cells) if info.get("test_dir") else (None, 0)
    if verb:
        return verb + (f" ×{n}" if n > 1 else "")
    todo = eels_item(eip, snap)
    return todo["action"] if todo else None


def eels_button(eip, info, cells, snap, extra="", action=""):
    state, short, text, _ = eels_state(info, cells, snap)
    return (f'<button type="button" class="chip {state}{extra}" data-open="{eip}-{EELS}"><span class="st">{glyph(state)}<span class="n">{E(short)}</span>'
            f'<span class="sr"> EIP-{eip} EELS: {E(text)}</span></span>{action}</button>')


def eels_cell(eip, info, cells, snap):
    state = eels_state(info, cells, snap)[0]
    return f'<td class="c eels {state}" id="c-{eip}-{EELS}">{eels_button(eip, info, cells, snap, "", action_html(eels_next(eip, info, cells, snap), "EELS"))}</td>'


def eels_drawer(eip, info, cells, snap):
    state, short, text, sub = eels_state(info, cells, snap)
    todo = eels_item(eip, snap)
    proven = {d["commit"] for c in cells for d in c["links"]["test"]["deltas"] if d["state"] == "covered"}
    links = ([a(todo["diff_url"], "EIP diff")] if todo and todo.get("diff_url") else []) + [a_local(eip_href(eip), "EIP page")]
    if info.get("test_dir"):
        links.append(a(test_dir_url(snap["newest_release"], info["test_dir"]), "tests"))
    rows = ""
    if info.get("deltas"):
        rows = kv("spec changes proven", f'<span class="num">{len(proven)}</span> of <span class="num">{len(info["deltas"])}</span> since the EELS pin') + "".join(
            kv("proven", f'<code>{a(gh(config.EIPS_REPO, "commit", d["commit"]), d["commit"][:8])}</code> {E(d["subject"])}') for d in info["deltas"] if d["commit"] in proven)
    why_text = eels_detail(todo, snap) if todo else f"EELS {release_short(snap['newest_release'])} implements the current EIP text."
    return (drawer_head(eip, "EELS", info.get("title") or eip_name(info))
            + f'<div class="dbig">{chip(state, short, " big")}<span class="dhl">{E(text)}</span><span class="muted">{E(sub)}</span></div>'
            + f'<p class="why">{E(why_text)}</p>' + next_line(eels_next(eip, info, cells, snap), "EELS")
            + f'<div class="dlinks">{" ".join(links)}</div>' + rows)


OWNER_LABEL = {**config.CLIENT_LABEL, EELS: "EELS"}


def owner_filter(shown):
    owners = [o for o in [*config.CLIENTS, EELS] if any(it["owner"] == o for it in shown)]
    opts = "".join(f'<option value="{o}">{E(OWNER_LABEL[o])} ({sum(it["owner"] == o for it in shown)})</option>' for o in owners)
    return (f'<p><label for="own">Owner</label> <select id="own" onchange="own(this.value)"><option value="">all ({len(shown)})</option>{opts}</select></p>')


def queue_html(snap, cells):
    items = queue(cells, tested(snap), snap["newest_release"])
    order = index.row_order(snap["eips"])
    kind_rank = {"run-fail": 0, "eels-update": 1, "open-delta": 2, "stale-release": 3, "run-missing": 4, "no-tests": 5}
    shown = sorted(items + eels_items(snap),
                   key=lambda it: (order.index(it["eip"]), kind_rank[it["kind"]]))
    out = [titlebar("Work queue", '<span class="muted">each item is one next action, highest-ranked EIP first</span>', "api/queue.json"),
           owner_filter(shown), '<div id="queue">']
    for i, it in enumerate(shown, 1):
        clients = ", ".join(config.CLIENT_LABEL[c] for c in it["clients"])
        if it["kind"] == "open-delta":
            info = snap["eips"][it["eip"]]
            delta = next(d for d in info["deltas"] if d["commit"] == it["commit"])
            cands = "".join(f'<div class="cand"><code>{E(t)}</code> <em>passes on: {", ".join(f"{config.CLIENT_LABEL[c]} {p}/{n}" for c, (p, n) in v.items())}</em></div>' for t, v in it["candidates"].items())
            body = (f'<span class="k warn">EIP-{it["eip"]} &middot; spec change untested</span> {a(gh(config.EIPS_REPO, "commit", it["commit"]), it["commit"][:8])} {E(delta["subject"])}'
                    f'<div class="muted">affects {E(clients)}</div>{constants_html(delta)}{cands}')
        elif it["kind"] == "eels-update":
            body = (f'<span class="k warn">EIP-{it["eip"]} &middot; tests behind the EIP text</span> {E(eels_detail(it, snap))} {a(it["diff_url"], "EIP diff")}'
                    + "".join(f'<div class="const"><code>{E(c["name"])}</code> {E(", ".join(c["before"]) or "none")} &rarr; <b>{E(", ".join(c["after"]) or "removed")}</b></div>'
                              for c in it["constants"]))
        elif it["kind"] == "no-tests":
            body = f'<span class="k none">EIP-{it["eip"]} &middot; no tests yet</span> {E(no_tests_text(snap["eips"][it["eip"]], snap))}'
        elif it["kind"] == "run-fail":
            body = (f'<span class="k bad">EIP-{it["eip"]} &middot; fail</span> {E(clients)}: {len(it["failed"])} failing'
                    + "".join(f'<div><code>{E(short_test(f))}</code></div>' for f in it["failed"][:3]))
        elif it["kind"] == "run-missing":
            body = f'<span class="k none">EIP-{it["eip"]} &middot; {E(MISSING_WORD[it["headline"]])}</span> {E(clients)} at {E(release_short(snap["newest_release"]))}'
        else:
            body = f'<span class="k stale">EIP-{it["eip"]} &middot; old tests</span> {E(clients)} last ran {E(release_short(it["release"]))}'
        cid = f'{it["eip"]}-{it["owner"]}'
        out.append(f'<div class="q" id="q{i}" data-owner="{it["owner"]}"><a class="act" href="index.html?view=action#{cid}" title="open the matrix cell">'
                   f'{E(it["verb"])} &middot; {E(OWNER_LABEL[it["owner"]])}</a>{body}'
                   + (f'<div class="muted">next: {E(it["action"])}</div>' if it["action"] != it["verb"] else "") + '</div>')
    out.append("</div>")
    return "".join(out), items, shown


def by_verb(items):
    counts = {}
    for it in items:
        counts[it["verb"]] = counts.get(it["verb"], 0) + 1
    return list(counts.items())


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def start_section(title, how, body):
    return f'<section class="start"><h3>{E(title)}</h3><p class="muted">{how}</p>{body}</section>'


def start_html(snap, cells, items):
    eels = [it for it in items if it["owner"] == EELS]
    rows = []
    for client in config.CLIENTS:
        parts = [f"{E(verb)} ({plural(n, 'EIP')})" for verb, n in by_verb([it for it in items if it["owner"] == client])]
        waiting = len({it["eip"] for it in eels if client in it["clients"]})
        if waiting:
            parts.append(f"{plural(waiting, 'EIP')} wait on the test team")
        rows.append(f'<tr><th class="row">{a_local(client_href(client), config.CLIENT_LABEL[client])}</th><td>{" &middot; ".join(parts) or "nothing to do"}</td></tr>')
    clients = start_section("What is my client missing today?",
                            "Open your client. Its To do list puts the most important item first.",
                            f'<div class="wrap"><table class="m list">{"".join(rows)}</table></div>')
    rows = []
    for eip in index.row_order(snap["eips"]):
        mine = [c for c in cells if c["eip"] == eip]
        state = counts_html(mine) if mine else '<span class="muted">no tests yet</span>'
        rows.append(f'<tr><th class="row">{a_local(eip_href(eip), "EIP-" + eip)}<small>{E(eip_name(snap["eips"][eip]))}</small></th>'
                    f'<td>{state} &middot; <a href="index.html#r-{eip}">matrix row</a></td></tr>')
    eips = start_section("Is this EIP really done?",
                         "Done means: the client's latest hive run on the newest EELS release passes, and every EIP change since the version EELS implements "
                         "is proven by a test or marked wording-only. Anything else stays open.",
                         f'<div class="wrap"><table class="m list">{"".join(rows)}</table></div>')
    if eels:
        verbs = ", ".join(f"{E(verb)} ({n})" for verb, n in by_verb(eels))
        body = f'<p>{plural(len(eels), "item")}: {verbs}. <a href="queue.html?owner=eels">Open the test team list</a>.</p>'
    else:
        body = '<p>nothing for the test team</p>'
    team = start_section("What do I tell the test team?",
                         "Each item names an EIP and the tests it needs. Every EIP page has a Copy as Markdown button for the message.", body)
    return (titlebar("Start here") + f'<p class="muted">Three questions a core dev asks, a minute each. Every number comes from the snapshot shown at the top.</p>'
            f'{clients}{eips}{team}')


def eels_items(snap):
    return [t for t in (eels_item(e, snap) for e in index.row_order(snap["eips"])) if t]


def site(snap, attestations, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cells = cells_for(snap, attestations)
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(page(f"{config.NAME} · {config.FORK}", "matrix", matrix_html(snap, cells), snap))
    qbody, items, shown = queue_html(snap, cells)
    with open(os.path.join(out_dir, "queue.html"), "w") as f:
        f.write(page(f"{config.NAME} · queue", "queue", qbody, snap))
    with open(os.path.join(out_dir, "start.html"), "w") as f:
        f.write(page(f"{config.NAME} · start here", "start", start_html(snap, cells, items + eels_items(snap)), snap))
    for sub in ("eip", "client"):
        os.makedirs(os.path.join(out_dir, "api", sub), exist_ok=True)
    rows = feed_rows(snap, attestations)
    pending = [{"eip": eip, **p} for eip in index.row_order(snap["eips"]) for p in handoff.pending_spec(snap, eip)]
    with open(os.path.join(out_dir, "changes.html"), "w") as f:
        f.write(page(f"{config.NAME} · spec changes", "changes", feed_html(snap, rows, pending), snap))
    with open(os.path.join(out_dir, "api", "changes.json"), "w") as f:
        json.dump({"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "changes": rows, "pending": pending}, f, indent=1, sort_keys=True)
    os.makedirs(os.path.join(out_dir, "api", "brief"), exist_ok=True)
    for c in cells:
        if c["headline"] != "pass":
            with open(os.path.join(out_dir, "api", "brief", f'{c["eip"]}-{c["client"]}.json'), "w") as f:
                json.dump(handoff.brief(c, snap, why(c, snap)), f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "api", "eips.json"), "w") as f:
        json.dump(eips_doc(snap), f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "api", "queue.json"), "w") as f:
        json.dump({"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "items": shown}, f, indent=1, sort_keys=True, default=str)
    for eip in index.row_order(snap["eips"]):
        with open(os.path.join(out_dir, eip_href(eip)), "w") as f:
            f.write(page(f"{config.NAME} · EIP-{eip}", "", eip_page_html(eip, snap, cells, attestations), snap))
        info = snap["eips"][eip]
        if not info.get("test_dir"):
            continue
        write_json(os.path.join(out_dir, "api", "eip", f"{eip}.json"), snap, [c for c in cells if c["eip"] == eip],
                   [it for it in items if it["eip"] == eip],
                   {"title": info.get("title"), "status": info.get("status"), "stage": info.get("stage"), "meta": snap.get("meta"),
                    "constants": {d["commit"]: d.get("constants", []) for d in info["deltas"]}}, eels_item(eip, snap))
    if snap.get("code_status") is not None:
        with open(os.path.join(out_dir, "api", "code.json"), "w") as f:
            json.dump({"fork": config.FORK, "snapshot": snap["taken_at"], "rule": "hint from file paths, file contents and PR titles that name the EIP; never changes a test verdict",
                       "eips": {eip: codepr.cells(snap, eip, attestations) for eip in index.row_order(snap["eips"])}}, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "releases.html"), "w") as f:
        f.write(page(f"{config.NAME} · test releases", "releases", releases_html(snap), snap))
    ddoc = diverge.doc(snap)
    with open(os.path.join(out_dir, "divergences.html"), "w") as f:
        f.write(page(f"{config.NAME} · divergences", "divergences", divergences_html(ddoc), snap))
    with open(os.path.join(out_dir, "api", "divergences.json"), "w") as f:
        json.dump(ddoc, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "api", "releases.json"), "w") as f:
        json.dump(releases_doc(snap), f, indent=1, sort_keys=True)
    pdoc = prs_doc(snap, cells)
    with open(os.path.join(out_dir, "prs.html"), "w") as f:
        f.write(page(f"{config.NAME} · PRs", "prs", prs_html(pdoc), snap))
    with open(os.path.join(out_dir, "api", "prs.json"), "w") as f:
        json.dump(pdoc, f, indent=1, sort_keys=True)
    for client in config.CLIENTS:
        with open(os.path.join(out_dir, client_href(client)), "w") as f:
            f.write(page(f"{config.NAME} · {config.CLIENT_LABEL[client]}", "", client_page_html(client, snap, cells, items), snap))
        write_json(os.path.join(out_dir, "api", "client", f"{client}.json"), snap, [c for c in cells if c["client"] == client],
                   [it for it in items if client in it["clients"]])
    return cells, items


DIVERGE_CLASS = {"match": "ok", "differs": "warn", "not-located": "none", "unparsed": "none", "spec-tbd": "none", "unreachable": "none"}


def divergence_cell(cell):
    word = cell["raw"] if cell["state"] in ("match", "differs") else cell["state"]
    text = a(cell["url"], word) if cell.get("url") else E(word)
    return f'<td class="c {DIVERGE_CLASS[cell["state"]]}" title="{E(cell.get("reason") or cell["state"])}">{text}</td>'


def divergences_html(doc):
    head = (titlebar("Divergences", '<span class="muted">client constants that differ from the EIP text</span>', "api/divergences.json")
            + f'<p class="muted">each value is read from the client source at the shown commit and compared with the constants table of the EIP on '
            f'{E(config.EIPS_BRANCH)}; a divergence is <b>suspect</b> until a hive run of that client fails tests of that EIP, then <b>confirmed</b>; '
            f'a suspect may be an old branch or a later spec change</p>')
    if not doc["eips"]:
        return head + '<p class="muted">no cross-client comparison in this snapshot</p>'
    rows = "".join(f'<div class="q"><span class="k {"bad" if r["status"] == "confirmed" else "warn"}">EIP-{E(r["eip"])} &middot; {E(r["status"])}</span> '
                   f'<code>{E(r["name"])}</code> spec <b>{r["spec"]}</b>, {E(config.CLIENT_LABEL[r["client"]])} <code>{E(r["ref"])}</code> has '
                   f'{a(r["url"], str(r["value"]))}'
                   + (f'<div class="muted">the branch commit is older than the spec change of {E(r["spec_since"]["date"][:10])}</div>' if r["predates_spec"] else "")
                   + '</div>' for r in doc["divergences"])
    out = [head, f'<h3>{plural(len(doc["divergences"]), "divergence")}</h3>', f'<div class="card">{rows}</div>' if rows else '<p class="muted">every located value matches the EIP text</p>']
    for e in doc["eips"]:
        names = [c["name"] for c in e["constants"]]
        thead = "<tr><th></th><th>EIP text</th>" + "".join(
            f'<th>{E(config.CLIENT_LABEL[r["client"]])}<small><code>{E(r["ref"])}</code>'
            + (f' {a(f"{config.GITHUB}/{r["repo"]}/pull/{r["pr"]}", "#" + str(r["pr"]))}' if r.get("pr") else "")
            + (f' &middot; {a(f"{config.GITHUB}/{r["repo"]}/commit/{r["sha"]}", r["sha"][:8])} {E((r["date"] or "")[:10])}' if r.get("sha") else f' &middot; {E(r["state"])}')
            + '</small></th>' for r in e["refs"]) + "</tr>"
        body = "".join(f'<tr><th class="row"><code>{E(c["name"])}</code></th><td class="c">{E(c["raw"] or "absent")}</td>'
                       + "".join(divergence_cell(r["cells"][c["name"]]) for r in e["refs"]) + "</tr>" for c in e["constants"])
        out.append(f'<h3 id="eip-{E(e["eip"])}">EIP-{E(e["eip"])} <span class="muted">{plural(len(names), "constant")}, EIP text at '
                   f'{a(e["spec"]["url"], e["spec"]["commit"][:8])} {E(e["spec"]["date"][:10])}</span></h3>'
                   f'<div class="wrap"><table class="m list">{thead}{body}</table></div>')
    return "".join(out)


def prs_doc(snap, cells):
    block = snap.get("pr_impact")
    base = {"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live")}
    if not block:
        return {**base, "state": "not-collected", "repo": config.CLIENT_REPO[impact.CLIENT], "prs": []}
    by = {(c["eip"], c["client"]): c for c in cells}
    client = block.get("client")
    rows = []
    for p in block["prs"]:
        eips = []
        for eip in index.row_order({e: snap["eips"][e] for e in p["evidence"] if e in snap["eips"]}):
            c = by.get((eip, client))
            eips.append({"eip": eip, "evidence": p["evidence"][eip],
                         "cell": c and {"client": client, "headline": c["headline"], "text": headline_text(c)},
                         "href": f"index.html#{eip}-{client}" if c else eip_href(eip)})
        if eips:
            rows.append({**{k: v for k, v in p.items() if k != "evidence"}, "eips": eips})
    return {**base, **{k: v for k, v in block.items() if k != "prs"}, "prs": rows}


def prs_html(doc):
    label = config.CLIENT_LABEL.get(doc.get("client"), doc["repo"])
    head = (titlebar(f"Open {E(label)} PRs", '<span class="muted">that name a tracked EIP or use one of its spec constants</span>', "api/prs.json")
            + f'<p class="muted">read from {a(f"{config.GITHUB}/{doc["repo"]}/pulls", doc["repo"])} on each rebuild: the title, the body and the changed lines of each open PR; '
            f'a match says the PR touches the EIP, not that it is correct &middot; run <code>{E(config.NAME)} pr-impact {E(doc["repo"])} &lt;pr&gt;</code> '
            f'for one PR</p>')
    if doc["state"] == "not-collected":
        return head + '<p class="muted">PRs not collected in this snapshot</p>'
    if doc["state"] != "ok":
        return head + f'<p class="muted">open PRs could not be listed in this snapshot ({E(doc.get("reason") or doc["state"])}); check the repo by hand</p>'
    notes = []
    if doc.get("unchecked"):
        notes.append(f'{plural(doc["unchecked"], "older open PR")} not checked')
    if doc.get("truncated"):
        notes.append("the open PR list hit the page cap")
    items = []
    for p in doc["prs"]:
        draft = ' <span class="pill none">draft</span>' if p.get("draft") else ""
        cut = ' <span class="muted">&middot; only the first changed files were read</span>' if p.get("files_truncated") else ""
        eips = "".join(f'<div class="sub">{a_local(e["href"], "EIP-" + e["eip"])} '
                       + (f'<span class="pill {CELL_PILL.get(e["cell"]["headline"], "none")}">{E(e["cell"]["text"])}</span> ' if e["cell"] else "")
                       + f'<span class="muted">{E(evidence_text(e["evidence"]))}</span></div>' for e in p["eips"])
        items.append(f'<div class="rev">{a(p["url"], "#" + str(p["number"]))} {E(p["title"])}{draft} '
                     f'<span class="muted">updated {E(p["updated"])}</span>{cut}{eips}</div>')
    body = f'<div class="card">{"".join(items)}</div>' if items else '<p class="muted">no open PR touches a tracked EIP</p>'
    return (head + f'<h3>{len(doc["prs"])} of {plural(doc.get("checked", 0), "checked open PR")}</h3>'
            + (f'<p class="muted">{E("; ".join(notes))}</p>' if notes else "") + body)


CELL_PILL = {"pass": "ok", "open": "warn", "stale-release": "warn", "fail": "bad"}


def evidence_text(rows):
    def one(ev):
        base = lambda p: p.rsplit("/", 1)[-1]
        k = ev["kind"]
        if k == "commit":
            return f'commit {ev["sha"][:8]}'
        if k == "path":
            return f'path {base(ev["file"])}'
        if k == "code":
            return f'{ev["token"]} in {base(ev["file"])}'
        if k == "constant":
            return ev["name"] + (f' as {ev["as"]}' if ev["as"] != ev["name"] else "") + f' in {base(ev["file"])}'
        return k
    return "; ".join(one(e) for e in rows[:6]) + (f"; and {len(rows) - 6} more" if len(rows) > 6 else "")


def releases_doc(snap):
    picked = {r["file"] for r in snap["runs"].values()}
    runs = [{**r, "in_matrix": r["file"] in picked} for r in snap.get("hive_runs") or []]
    known = {r["tag"] for r in snap.get("releases") or []}
    rows = [{**rel, "newest": rel["tag"] == snap["newest_release"],
             "runs": {c: [r for r in runs if r["release"] == rel["tag"] and r["client"] == c] for c in config.CLIENTS}}
            for rel in snap.get("releases") or []]
    return {"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "newest_release": snap["newest_release"],
            "simulator": config.SIMULATOR, "hive": config.HIVE, "releases": rows, "other_runs": [r for r in runs if r["release"] not in known]}


def release_cell(runs):
    if not runs:
        return '<td class="c none"><div class="hl">no run</div></td>'
    last = runs[0]
    passed = last["ntests"] - last["fails"]
    state = "ok" if not last["fails"] else "bad" if last["fails"] / last["ntests"] > config.INFRA_FAIL_RATIO else "warn"
    mark = ' <span class="pill ok">in matrix</span>' if any(r["in_matrix"] for r in runs) else ""
    return (f'<td class="c {state}"><a class="hl" href="{E(last["url"])}" target="_blank" rel="noopener">pass {passed}/{last["ntests"]}</a>'
            f'<div class="sub">{plural(len(runs), "run")} &middot; last {E(last["start"][:10])}{mark}</div></td>')


def releases_html(snap):
    doc = releases_doc(snap)
    head = "<tr><th></th>" + "".join(f"<th>{a_local(client_href(c), config.CLIENT_LABEL[c])}</th>" for c in config.CLIENTS) + "</tr>"
    rows = []
    for rel in doc["releases"]:
        pill = ' <span class="pill ok">newest</span>' if rel["newest"] else ""
        rows.append(f'<tr id="{E(release_short(rel["tag"]))}"><th class="row">{a(rel["url"], release_short(rel["tag"]))}{pill}'
                    f'<small>{E(rel["date"][:10])} &middot; <code>{a(gh(config.EELS_REPO, "commit", rel["commit"]), rel["commit"][:8])}</code></small></th>'
                    + "".join(release_cell(rel["runs"][c]) for c in config.CLIENTS) + "</tr>")
    other = ""
    if doc["other_runs"]:
        other = (f'<h3>{plural(len(doc["other_runs"]), "run")} with an unknown or other release</h3><div class="card">'
                 + "".join(f'<div class="rev">{E(config.CLIENT_LABEL[r["client"]])} {a(r["url"], r["start"][:16].replace("T", " "))} '
                           f'<span class="muted">{E(r["release"] or "release not in sim log")} &middot; pass {r["ntests"] - r["fails"]}/{r["ntests"]}</span></div>'
                           for r in doc["other_runs"]) + "</div>")
    if not doc["releases"]:
        return titlebar("Test releases", "", "api/releases.json") + '<p class="muted">this snapshot has no release list</p>'
    return (titlebar("Test releases", f'<span class="muted">each {E(config.RELEASE_PREFIX)}* release and the {E(config.SIMULATOR)} runs that used it in hive</span>', "api/releases.json")
            + f'<p class="muted">a cell shows the newest run of that client on that release; "in matrix" marks the run the matrix uses</p>'
            f'<div class="wrap"><table class="m list">{head}{"".join(rows)}</table></div>{other}')


def history_html(entries):
    items = []
    for e in entries:
        link = a_local(e["href"], e["taken_at"]) if e.get("href") else a(e["json"], e["taken_at"])
        items.append(f'<div class="rev">{link} <span class="muted">newest release {E(release_short(e["newest_release"]))} &middot; '
                     f'{plural(e["runs"], "client run")}</span>{" " + a(e["json"], "JSON") if e.get("href") and e.get("json") else ""}</div>')
    return (titlebar("Snapshot history", '<span class="muted">one entry per change in the data, newest first</span>', "api/history.json")
            + f'<p class="muted">each link opens the site as it was for that snapshot, shown with the current code and proofs; '
            f'older snapshots link to their JSON on the {a(gh(config.SELF_REPO, "tree", config.DATA_BRANCH), config.DATA_BRANCH)} branch</p>'
            f'<div class="card">{"".join(items)}</div>')


def eips_doc(snap):
    rows = []
    for eip in index.row_order(snap["eips"]):
        info = snap["eips"][eip]
        rows.append({"eip": eip, "title": info.get("title"), "status": info.get("status"), "category": info.get("category"),
                     "stage": info.get("stage") or [], "test_dir": info.get("test_dir"), "checked": info.get("checked"), "head": info.get("head"),
                     "behind": len(info["deltas"]) if info.get("pin") else None, "eels_todo": eels_item(eip, snap), "page": f'{config.SITE_URL}/{eip_href(eip)}'})
    return {"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "newest_release": snap["newest_release"],
            "meta": snap.get("meta"), "eips": rows}


def write_json(path, snap, cells, items, spec=None, eels=None):
    doc = {"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "newest_release": snap["newest_release"], "listing_url": snap["listing_url"],
           "cells": [{"eip": c["eip"], "client": c["client"], "headline": c["headline"], "text": headline_text(c), "why": why(c, snap),
                      "links": {k: v for k, v in c["links"].items() if not k.startswith("_")}} for c in cells],
           "todo": items}
    if spec is not None:
        doc["spec"] = spec
        doc["eels_todo"] = eels
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True, default=str)
