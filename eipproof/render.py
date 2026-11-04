import html
import json
import os
import re
from datetime import datetime

from . import config, index
from .chain import chain, headline_text, queue, release_short

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


def a(url, text, cls=""):
    return f'<a href="{E(url)}" target="_blank" rel="noopener"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{E(text)}</a>'


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
        return f"{len(run['failed'])} test(s) for this EIP failed in {label}'s run on {release_short(run['release'])}. Next: fix the client or report the test."
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
        return (f"The run passed {run['passed']}/{run['total']}, but the EIP text changed {spec['behind']} time(s) since the "
                f"version EELS implements, and {n} change(s) have {gap}.{tail} Next: {nxt}.")
    if h == "pass":
        proven = [d for d in test["deltas"] if d["state"] == "covered"]
        if proven:
            return (f"All {run['total']} tests for this EIP passed on {release_short(run['release'])}. "
                    f"The EIP text changed {spec['behind']} time(s) since the version EELS implements. For each change, a spec "
                    f"with the change undone fails {', '.join(str(d['cases']) for d in proven)} case(s) in EELS, and those cases pass here.")
        return f"All {run['total']} tests for this EIP passed on {release_short(run['release'])}, and EELS implements the current EIP text."
    if h == "no-tests":
        return f"{label}'s run on {release_short(run['release'])} has no cases in this EIP's test directory."
    return f"No {config.SIMULATOR} run for {label}."


def dots(cell):
    out = []
    for key in ("spec", "test", "run"):
        st = cell["links"][key]["state"]
        out.append(f'<i class="dot {STATE_CLASS.get(st, "none")}" title="{DOT[key]}: {E(LABEL.get(st, st))}"></i>')
    return '<span class="dots">' + "".join(out) + "</span>"


def md(url, text):
    return f"[{text}]({url})"


def copy_md(text):
    return (f'<div class="copy"><button type="button" onclick="copyMd(this)">Copy as Markdown</button>'
            f'<textarea class="md" readonly hidden aria-label="Markdown">{E(text)}</textarea></div>')


def cell_markdown(cell, snap):
    info = snap["eips"][cell["eip"]]
    s, t, r = cell["links"]["spec"], cell["links"]["test"], cell["links"]["run"]
    subjects = {d["commit"]: d["subject"] for d in info["deltas"]}
    pin = md(gh(config.EIPS_REPO, "commit", s["pin_commit"]), s["pin_commit"][:8]) if s["pin_commit"] else "?"
    lines = [f'**EIP-{cell["eip"]} x {config.CLIENT_LABEL[cell["client"]]}: {headline_text(cell)}**', "", why(cell, snap), "",
             f'- Spec: EIP now {md(gh(config.EIPS_REPO, "commit", info["head"]), info["head"][:8])}; EELS '
             f'{release_short(info["pin"]["release"])} implements {pin}' + (f', {s["behind"]} change(s) behind' if s["behind"] else ", current")]
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
    lines += ["", "Spec changes, newest first:"]
    for rev in reversed(info["revisions"]):
        lines.append(f'- {md(gh(config.EIPS_REPO, "commit", rev["commit"]), rev["commit"][:8])} {rev["date"][:10]} '
                     f'{rev["subject"]}: {rev_state(eip, info, rev, attestations)[1]}')
    lines += ["", f'{md(f"{config.GITHUB}/{config.EIPS_REPO}/blob/{config.EIPS_BRANCH}/{info["path"]}", "EIP text")} · '
                  f'{md(f"{config.SITE_URL}/{eip_href(eip)}", "eipproof page")}']
    return "\n".join(lines) + "\n"


def link_block(n, title, state, body):
    return (f'<section class="link {STATE_CLASS.get(state, "none")}"><header><b>{n}</b> {E(title)}'
            f'<span class="pill {STATE_CLASS.get(state, "none")}">{E(LABEL.get(state, state))}</span></header>{body}</section>')


def added_lines(diff):
    return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]


def tokens_marked(text, tokens):
    out = E(text)
    for t in tokens:
        out = out.replace(E(t), f"<mark>{E(t)}</mark>")
    return out


def spec_html(cell, eip_info):
    s = cell["links"]["spec"]
    rows = [f'<div class="kv"><span>EIP now</span><code>{a(gh(config.EIPS_REPO, "commit", eip_info["head"]), eip_info["head"][:8])}</code> {E(eip_info["head_date"][:10])}</div>',
            f'<div class="kv"><span>EELS has</span><code>{a(eip_info["pin"]["spec_py"], s["pin_blob"][:8])}</code> = EIPs '
            f'<code>{a(gh(config.EIPS_REPO, "commit", s["pin_commit"]), s["pin_commit"][:8]) if s["pin_commit"] else "?"}</code>'
            f' at {E(release_short(eip_info["pin"]["release"]))} '
            + (f'<span class="pill warn">{s["behind"]} change(s) behind</span>' if s["behind"] else '<span class="pill ok">current</span>')
            + (' <span class="pill none">same text in several commits</span>' if s["pin_ambiguous"] else "") + "</div>"]
    for p in s["pending"]:
        rows.append(f'<div class="overlay" data-mark="pending"><span class="pill none">open PR</span> {a(p["url"], "EIPs#" + str(p["number"]))} '
                    f'{E(p["title"])} <em>not merged, not counted</em></div>')
    return link_block(1, "Spec: does EELS implement the current EIP text?", s["state"], "".join(rows))


def test_html(cell, eip_info):
    t = cell["links"]["test"]
    if t["state"] == "n/a":
        return link_block(2, "Tests: does a test catch each spec change?", "n/a",
                          '<p class="muted">n/a: this run used old tests, so proofs for the current tests do not apply.</p>')
    if not t["deltas"]:
        return link_block(2, "Tests: does a test catch each spec change?", "pass", '<p class="muted">EELS implements the current EIP text: no change to prove.</p>')
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
        rows.append(f'<div class="delta" data-mark="delta"><div class="kv"><span>change</span><code>{a(gh(config.EIPS_REPO, "commit", d["commit"]), d["commit"][:8])}</code> '
                    f'{E(info["date"][:10])} {E(info["subject"])} <span class="pill {STATE_CLASS.get(d["state"], "none")}">{E(LABEL.get(d["state"], d["state"]))}</span></div>'
                    f'{constants_html(info)}<div class="diff">{diff}</div>{cands}{att}</div>')
    return link_block(2, "Tests: does a test catch each spec change?", t["state"], "".join(rows))


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
    kills = "".join(f'<div><code>{E(short_test(k))}</code></div>' for k in at["killed"])
    return (f'<div class="att" data-mark="att"><span class="pill ok">proven</span> a {mutant} undoes the change; in EELS '
            f'{E(release_short(at["eels"]["ref"]))} it fails {len(at["killed"])} of {at["baseline"]["cases"]} cases '
            f'<em>({E(at["date"])})</em>{kills}</div>')


def run_html(cell, run_full):
    r = cell["links"]["run"]
    if r["state"] == "no-run":
        return link_block(3, "Run: does the client pass the tests?", "no-run", '<p class="muted">no run</p>')
    count = f'<b class="big">{r["passed"]}/{r["total"]}</b>'
    body = [f'<div class="kv" data-mark="count"><span>result</span>{count} cases in <code>{E(eip_dir_name(cell))}</code></div>',
            f'<div class="kv" data-mark="release"><span>tests</span><code>{E(r["release"])}</code>'
            + (f' <span class="pill stale">newest is {E(release_short(r["newest_release"]))}</span>' if r["state"] == "stale-release" else "") + "</div>",
            f'<div class="kv"><span>image</span><code>{E(r["image"] or "?")}</code></div>',
            f'<div class="kv"><span>version</span><code>{E(r["version"])}</code></div>',
            f'<div class="kv"><span>run</span>{E(run_full["start"][:16].replace("T", " "))}Z &rarr; {a(r["url"], "hive run")} &middot; {a(run_full["sim_log"], "sim log")}</div>']
    if r["failed"]:
        body.append('<div class="fails" data-mark="fails">' + "".join(f"<div><code>{E(short_test(f))}</code></div>" for f in r["failed"][:8]) + "</div>")
    return link_block(3, "Run: does the client pass the tests?", r["state"], "".join(body))


def eip_dir_name(cell):
    return cell["links"]["_dir"]


def drawer(cell, snap):
    eip_info = snap["eips"][cell["eip"]]
    run_full = snap["runs"].get(cell["client"], {})
    h = cell["headline"]
    return (f'<div class="dhead"><div><div class="muted">EIP-{cell["eip"]} &times; {E(config.CLIENT_LABEL[cell["client"]])}</div>'
            f'<div class="headline {STATE_CLASS[h]}" data-mark="headline">{E(headline_text(cell))}</div></div><button class="x" onclick="closeD()" aria-label="Close">&times;</button></div>'
            f'<p class="why" data-mark="why">{E(why(cell, snap))}</p>{copy_md(cell_markdown(cell, snap))}'
            + spec_html(cell, eip_info) + test_html(cell, eip_info) + run_html(cell, run_full))


CSS = """
:root{--bg:#0b0f17;--card:#111827;--line:#1f2937;--fg:#e5e7eb;--mut:#8b95a7;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--stale:#818cf8;--none:#4b5563;--edit:#38bdf8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI","DejaVu Sans",sans-serif}
a{color:#93c5fd;text-decoration:none}a:hover{text-decoration:underline}code{font:13px "DejaVu Sans Mono",monospace;color:#cbd5e1}
header.top{display:flex;align-items:center;gap:18px;padding:16px 28px;border-bottom:1px solid var(--line)}
.brand{font-weight:800;font-size:20px;letter-spacing:.2px}.brand span{color:var(--ok)}
nav a{margin-right:14px;color:var(--mut)}nav a.on{color:var(--fg);font-weight:600}
.meta{margin-left:auto;color:var(--mut);font-size:13px;text-align:right}
main{padding:20px 28px}.strip{background:#1a1320;border:1px solid #3b1d2a;border-radius:10px;padding:8px 12px;margin-bottom:14px;font-size:13px;color:#fca5a5}
table.m{border-collapse:separate;border-spacing:6px;width:100%}th{color:var(--mut);font-weight:600;font-size:13px;text-align:left;padding:0 8px}
th.row{width:150px}th.row a{color:var(--fg);font-size:15px}th.row small{display:block;color:var(--mut);font-weight:400;font-size:12.5px}th small{font-size:12px}
.wrap{overflow-x:auto}table td.c:focus-visible,a:focus-visible,.x:focus-visible{outline:2px solid #93c5fd;outline-offset:2px}
h2{text-wrap:balance;font-size:22px}.q code,.cand code,.att code,.fails code,.kv code{overflow-wrap:anywhere}
td.c{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer;transition:.15s;vertical-align:top}
td.c:hover{border-color:#475569;transform:translateY(-1px)}table td.c.sel{outline:2px solid #e5e7eb;outline-offset:-1px}
.hl{font-weight:700;font-size:15px}.ok .hl,.hl.ok{color:var(--ok)}.warn .hl,.hl.warn{color:var(--warn)}.bad .hl{color:var(--bad)}.stale .hl{color:var(--stale)}.none .hl{color:var(--mut)}
td.c.ok{outline:1px solid var(--ok);outline-offset:-3px}td.c.warn{outline:1px solid var(--warn);outline-offset:-3px}td.c.bad{outline:1px solid var(--bad);outline-offset:-3px}td.c.stale{outline:1px solid var(--stale);outline-offset:-3px}td.c.none{outline:1px solid var(--none);outline-offset:-3px}
.sub{color:var(--mut);font-size:12px;margin-top:2px}.dots{float:right;margin-top:4px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-left:4px;background:var(--none)}
.dot.ok{background:var(--ok)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}.dot.stale{background:var(--stale)}.dot.edit{background:var(--edit)}
.stage{font-size:12px;color:#8b95a7;margin-top:2px}.sb{font-size:11px;padding:0 5px;margin-right:4px}.cov{margin:4px 0 10px}.stage a{color:inherit}.consts{margin:4px 0;font-size:13px}.const code{color:var(--warn)}
.badge{display:inline-block;font-size:12px;line-height:1.3;padding:4px 8px;border-radius:99px;background:#2a2112;color:var(--warn);margin-top:4px}
.legend{color:var(--mut);font-size:13px;margin:14px 6px}.legend i{margin:0 4px 0 12px}
#d{position:fixed;top:0;right:0;height:100%;width:min(640px,100vw);background:#0f1522;border-left:1px solid var(--line);transform:translateX(100%);transition:transform .35s ease;overflow:auto;padding:20px 24px;box-shadow:-20px 0 40px #0008}
#d.on{transform:none}.dhead{display:flex;justify-content:space-between}.x{background:none;border:0;color:var(--mut);font-size:28px;cursor:pointer}
.headline{font-size:26px;font-weight:800}.headline.ok{color:var(--ok)}.headline.warn{color:var(--warn)}.headline.bad{color:var(--bad)}.headline.stale{color:var(--stale)}.headline.none{color:var(--mut)}
.why{color:#cbd5e1;background:#151d2c;border-radius:10px;padding:10px 12px;margin:12px 0}
section.link{border:1px solid var(--none);border-radius:10px;padding:10px 12px;margin:10px 0;background:var(--card)}
section.link.ok{border-color:var(--ok)}section.link.warn{border-color:var(--warn)}section.link.bad{border-color:var(--bad)}section.link.stale{border-color:var(--stale)}
section.link header{display:flex;gap:8px;align-items:center;font-weight:700;margin-bottom:6px}section.link header .pill{margin-left:auto}
.pill{font-size:11px;padding:1px 8px;border-radius:99px;background:#1f2937;color:var(--mut);font-weight:600}.pill.ok{background:#0f2a1a;color:var(--ok)}.pill.warn{background:#2a2112;color:var(--warn)}.pill.bad{background:#2a1212;color:var(--bad)}.pill.stale{background:#1c1d3a;color:var(--stale)}
.kv{margin:3px 0}.kv>span:first-child{display:inline-block;width:78px;color:var(--mut);font-size:13px}.big{font-size:20px;color:var(--fg)}
.diff{background:#0b1220;border-radius:8px;padding:6px 10px;margin:6px 0;font-size:13px}.add{color:#bbf7d0}mark{background:#3b3412;color:#fde68a;border-radius:3px;padding:0 2px}
.cand,.att,.overlay{margin:6px 0;font-size:13.5px}.overlay{color:var(--mut)}em{color:var(--mut);font-style:normal}.muted{color:var(--mut)}
.fails{font-size:12.5px;max-height:150px;overflow:auto;background:#1a1010;border-radius:8px;padding:6px 10px}
.q{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:10px 0}.q .k{font-weight:700}.q .k.bad{color:var(--bad)}.q .k.warn{color:var(--warn)}.q .k.stale{color:var(--stale)}
.q .act{float:right;font-size:13px;color:#0b0f17;background:var(--fg);padding:2px 10px;border-radius:99px;margin:0 0 6px 8px}
h3{font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);margin:22px 0 8px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.rev{margin:4px 0;font-size:14px}table.list td.c{cursor:default;width:190px}table.list td.c:hover{transform:none}a.hl{display:block}
td.why-cell{color:#cbd5e1;font-size:13.5px;vertical-align:top;padding:8px 10px}.why-cell p{margin:0;max-width:62ch;text-wrap:pretty}tr.counts th{font-weight:400;padding-top:0}tr.counts small .hl{font-size:12px}.hl.bad{color:var(--bad)}.hl.stale{color:var(--stale)}.hl.none{color:var(--mut)}
[hidden]{display:none!important}.strip.age{background:#2a2112;border-color:#4a3a14;color:var(--warn)}
.copy{margin:8px 0}.copy button{font:inherit;font-size:13px;color:var(--fg);background:#1f2937;border:1px solid var(--line);border-radius:99px;padding:3px 12px;cursor:pointer}
.copy button:hover{border-color:#475569}.copy textarea{display:block;width:100%;height:180px;margin-top:6px;background:#0b1220;color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px;font:12.5px "DejaVu Sans Mono",monospace}
select{font:inherit;font-size:14px;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:4px 8px}label{color:var(--mut);font-size:13px}
.copy button:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid #93c5fd;outline-offset:2px}
@media (max-width:700px){table.list tr{display:block;margin-bottom:10px}table.list th,table.list td{display:block;width:auto}header.top{flex-wrap:wrap;padding:12px 16px}.meta{margin-left:0;text-align:left}main{padding:14px 12px}th.row{width:auto}#d{padding:16px}.q .act{float:none;display:inline-block}}
"""

JS = """
function openD(id,el){document.querySelectorAll('td.c.sel').forEach(x=>x.classList.remove('sel'));if(el)el.classList.add('sel');
document.getElementById('dc').innerHTML=document.getElementById('t-'+id).innerHTML;document.getElementById('d').classList.add('on');history.replaceState(null,'','#'+id)}
function closeD(){document.getElementById('d').classList.remove('on');document.querySelectorAll('td.c.sel').forEach(x=>x.classList.remove('sel'));history.replaceState(null,'',location.pathname)}
addEventListener('keydown',e=>{if(e.key==='Escape')closeD();else if((e.key==='Enter'||e.key===' ')&&e.target.matches('td.c')){e.preventDefault();e.target.click()}});
addEventListener('load',()=>{const h=location.hash.slice(1);if(h&&document.getElementById('t-'+h))openD(h,document.getElementById('c-'+h));
const f=document.getElementById('f');if(f&&h.startsWith('eip-')&&f.querySelector('option[value="'+h.slice(4)+'"]')){f.value=h.slice(4);filt(f.value)}
const s=document.getElementById('stale'),t=s&&staleText(s.dataset.taken,Date.now());if(t){s.textContent=t;s.hidden=false}});
function staleText(taken,now){const h=(now-Date.parse(taken))/36e5;return h>6?'data from snapshot '+taken.slice(0,16).replace('T',' ')+' UTC, '+Math.floor(h)+' h old: newer runs or spec changes may exist':''}
function filt(v){document.querySelectorAll('#feed .rev').forEach(r=>r.hidden=!!v&&r.dataset.eip!==v);history.replaceState(null,'',v?'#eip-'+v:location.pathname)}
function copyMd(b){const t=b.nextElementSibling,show=()=>{t.hidden=false;t.select()};if(!navigator.clipboard)return show();
navigator.clipboard.writeText(t.value).then(()=>{b.textContent='Copied';setTimeout(()=>{b.textContent='Copy as Markdown'},1500)},show)}
"""


COUNT_WORD = {"pass": "pass", "open": "untested", "stale-release": "old tests", "fail": "fails", "no-run": "no run", "no-tests": "no tests"}
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
    return f'<p class="muted cov" data-mark="coverage">{line} &middot; {a_local("api/eips.json", "JSON")}</p>'


def headline_counts(cells):
    counts = {}
    for c in cells:
        counts[c["headline"]] = counts.get(c["headline"], 0) + 1
    return [(h, counts[h]) for h in COUNT_ORDER if h in counts]


def counts_html(cells):
    return " &middot; ".join(f'<span class="hl {STATE_CLASS[h]}">{n} {E(COUNT_WORD[h])}</span>' for h, n in headline_counts(cells))


def delta_word(eip, commit, attestations):
    mine = [a for a in attestations if a["eip"] == eip and commit.startswith(str(a["commit"]))]
    if not mine:
        return "open"
    at = mine[-1]
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


def untested_page_html(eip, snap, attestations):
    info = snap["eips"][eip]
    timeline = "".join(f'<div class="rev"><code>{a(gh(config.EIPS_REPO, "commit", rev["commit"]), rev["commit"][:8])}</code> '
                       f'<span class="muted">{E(rev["date"][:10])}</span> {E(rev["subject"])}</div>' for rev in reversed(info["revisions"]))
    pend = "".join(f'<div class="overlay"><span class="pill none">open PR</span> {a(p["url"], "EIPs#" + str(p["number"]))} {E(p["title"])} '
                   f'<em>not merged, not counted</em></div>' for p in info["pending"])
    return (f'<h2>EIP-{eip} <span class="muted">{E(info.get("title") or "")}</span></h2>{stage_html(info, snap)}'
            f'<p class="muted">{a(f"{config.GITHUB}/{config.EIPS_REPO}/blob/{config.EIPS_BRANCH}/{info["path"]}", "EIP text")} &middot; '
            f'{a_local(f"changes.html#eip-{eip}", "all spec changes")} &middot; {a_local("api/eips.json", "JSON")}</p>'
            f'<div class="card" data-mark="no-tests"><b>no tests yet</b> <span class="muted">{E(no_tests_text(info, snap))}. '
            f'No client cell is shown: there is nothing to run.</span></div>'
            f'<h3>Spec changes, newest first</h3><div class="card">{timeline}</div>'
            + (f'<h3>Open EIP PRs</h3><div class="card">{pend}</div>' if pend else ""))


def eip_page_html(eip, snap, cells, attestations):
    info = snap["eips"][eip]
    if not info.get("test_dir"):
        return untested_page_html(eip, snap, attestations)
    mine = [c for c in cells if c["eip"] == eip]
    deltas = {d["commit"]: d for d in info["deltas"]}
    rows = []
    for c in mine:
        r = c["links"]["run"]
        tests = E(release_short(r.get("release"))) if r["state"] != "no-run" else "-"
        rows.append(f'<tr><th class="row">{a_local(client_href(c["client"]), config.CLIENT_LABEL[c["client"]])}</th>'
                    f'<td class="c {STATE_CLASS[c["headline"]]}"><a class="hl" href="index.html#{eip}-{c["client"]}">{E(headline_text(c))}</a>'
                    f'<div class="sub">tests {tests}</div></td><td class="why-cell"><p>{E(why(c, snap))}</p></td></tr>')
    timeline = []
    for rev in reversed(info["revisions"]):
        st, word = rev_state(eip, info, rev, attestations)
        consts = constants_html(deltas[rev["commit"]]) if rev["commit"] in deltas else ""
        timeline.append(f'<div class="rev"><code>{a(gh(config.EIPS_REPO, "commit", rev["commit"]), rev["commit"][:8])}</code> '
                        f'<span class="muted">{E(rev["date"][:10])}</span> {E(rev["subject"])} <span class="pill {STATE_CLASS[st]}">{E(word)}</span>{consts}</div>')
    pend = "".join(f'<div class="overlay"><span class="pill none">open PR</span> {a(p["url"], "EIPs#" + str(p["number"]))} {E(p["title"])} '
                   f'<em>not merged, not counted</em></div>' for p in info["pending"])
    return (f'<h2>EIP-{eip} <span class="muted">{E(info.get("title") or eip_name(info))}</span></h2>{stage_html(info, snap)}'
            f'<p class="muted">{a(f"{config.GITHUB}/{config.EIPS_REPO}/blob/{config.EIPS_BRANCH}/{info["path"]}", "EIP text")} &middot; '
            f'{a(f"{config.GITHUB}/{config.EELS_REPO}/tree/{info["pin"]["release"].replace("@", "%40")}/{info["test_dir"]}", "EELS tests")} &middot; '
            f'{a_local(f"changes.html#eip-{eip}", "all spec changes")} &middot; {a_local(f"api/eip/{eip}.json", "JSON")}</p>'
            f'{copy_md(eip_markdown(eip, snap, cells, attestations))}'
            f'<h3>Clients</h3><div class="wrap"><table class="m list">{"".join(rows)}</table></div>'
            f'<h3>Spec changes, newest first</h3><div class="card">{"".join(timeline)}</div>'
            + (f'<h3>Open EIP PRs</h3><div class="card">{pend}</div>' if pend else ""))


def client_page_html(client, snap, cells, items):
    label = config.CLIENT_LABEL[client]
    mine = [c for c in cells if c["client"] == client]
    run = snap["runs"].get(client)
    if run:
        stale = (f' <span class="pill stale">newest is {E(release_short(snap["newest_release"]))}</span>'
                 if run["release"] != snap["newest_release"] else "")
        receipt = (f'<div class="card"><div class="kv"><span>tests</span><code>{E(run["release"])}</code>{stale}</div>'
                   f'<div class="kv"><span>image</span><code>{E(run["image"] or "?")}</code></div>'
                   f'<div class="kv"><span>version</span><code>{E(run["version"])}</code></div>'
                   f'<div class="kv"><span>run</span>{E(run["start"][:16].replace("T", " "))}Z &rarr; {a(run["url"], "hive run")} &middot; {a(run["sim_log"], "sim log")}</div>'
                   f'<div class="kv"><span>outside</span>{len(run["client_wide_failures"])} failing case(s) outside the tracked EIP dirs, not counted</div></div>')
    else:
        receipt = f'<div class="card muted">No {E(config.SIMULATOR)} run for {E(label)}.</div>'
    todo = [it for it in items if client in it["clients"]]
    todo_html = "".join(f'<div class="q"><a class="act" href="index.html#{it["eip"]}-{client}">{E(it["action"])}</a>'
                        f'<span class="k {STATE_CLASS[QUEUE_STATE[it["kind"]]]}">EIP-{it["eip"]} &middot; {E(QUEUE_WORD[it["kind"]])}</span> '
                        f'{E(queue_detail(it, snap))}</div>' for it in todo) or '<p class="muted">Nothing to do: every tracked EIP passes on the newest tests.</p>'
    rows = "".join(f'<tr><th class="row">{a_local(eip_href(c["eip"]), "EIP-" + c["eip"])}<small>{E(eip_name(snap["eips"][c["eip"]]))}</small></th>'
                   f'<td class="c {STATE_CLASS[c["headline"]]}"><a class="hl" href="index.html#{c["eip"]}-{client}">{E(headline_text(c))}</a></td>'
                   f'<td class="why-cell"><p>{E(why(c, snap))}</p></td></tr>' for c in mine)
    return (f'<h2>{E(label)} <span class="muted">{counts_html(mine)}</span></h2>'
            f'<p class="muted">{a(f"{config.GITHUB}/{config.CLIENT_REPO[client]}", config.CLIENT_REPO[client])} &middot; {a_local(f"api/client/{client}.json", "JSON")}</p>'
            f'<h3>To do, most important first</h3>{todo_html}'
            f'<h3>Run</h3>{receipt}'
            f'<h3>EIPs</h3><div class="wrap"><table class="m list">{rows}</table></div>')


QUEUE_STATE = {"run-fail": "fail", "open-delta": "open", "stale-release": "stale-release"}
QUEUE_WORD = {"run-fail": "fails", "open-delta": "spec change untested", "stale-release": "old tests"}


def queue_detail(it, snap):
    if it["kind"] == "run-fail":
        return f'{len(it["failed"])} failing: ' + ", ".join(short_test(f) for f in it["failed"][:3])
    if it["kind"] == "open-delta":
        delta = next(d for d in snap["eips"][it["eip"]]["deltas"] if d["commit"] == it["commit"])
        return f'{it["commit"][:8]} {delta["subject"]}'
    return f'last ran {release_short(it["release"])}'


def a_local(href, text):
    return f'<a href="{E(href)}">{E(text)}</a>'


def feed_rows(snap, attestations):
    rows = []
    for eip in index.row_order(snap["eips"]):
        info = snap["eips"][eip]
        for rev in info["revisions"]:
            st, word = rev_state(eip, info, rev, attestations)
            rows.append({"eip": eip, "commit": rev["commit"], "date": rev["date"], "subject": rev["subject"], "state": st, "word": word,
                         "url": gh(config.EIPS_REPO, "commit", rev["commit"])})
    return sorted(rows, key=lambda r: (datetime.fromisoformat(r["date"]), r["eip"], r["commit"]), reverse=True)


def feed_html(snap, rows):
    eips = index.row_order(snap["eips"])
    opts = '<option value="">all EIPs</option>' + "".join(
        f'<option value="{e}">EIP-{e} ({sum(r["eip"] == e for r in rows)})</option>' for e in eips)
    items = "".join(f'<div class="rev" data-eip="{r["eip"]}">{a_local(eip_href(r["eip"]), "EIP-" + r["eip"])} '
                    f'<code>{a(r["url"], r["commit"][:8])}</code> <span class="muted">{E(r["date"][:10])}</span> {E(r["subject"])} '
                    f'<span class="pill {STATE_CLASS[r["state"]]}">{E(r["word"])}</span></div>' for r in rows)
    return (f'<h2>Spec changes <span class="muted">every change to a tracked EIP text, newest first</span></h2>'
            f'<p class="muted">proven: a spec with the change undone fails a test, and EELS has that test &middot; untested: no proof yet '
            f'&middot; wording only: no behaviour &middot; older: EELS already implements a later text &middot; {a_local("api/changes.json", "JSON")}</p>'
            f'<p><label for="f">Show</label> <select id="f" onchange="filt(this.value)">{opts}</select></p>'
            f'<div class="card" id="feed">{items}</div>')


def stale_banner(snap):
    return f'<div class="strip age" id="stale" role="status" hidden data-taken="{E(snap["taken_at"])}"></div>'


def fallback_banner(snap):
    if snap.get("source") != "snapshot":
        return ""
    return (f'<div class="strip" id="fallback" role="alert">data from snapshot {E(snap["taken_at"][:10])}: '
            f'the live rebuild did not run, so this page may be out of date</div>')


def page(title, nav, body, snap):
    links = "".join(f'<a href="{href}" class="{"on" if key == nav else ""}">{E(label)}</a>' for key, href, label in
                    [("matrix", "index.html", "Matrix"), ("queue", "queue.html", "Work queue"), ("changes", "changes.html", "Spec changes")])
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(title)}</title><style>{CSS}</style></head><body>'
            f'<header class="top"><div class="brand">{E(config.NAME)}<span>.</span></div><nav>{links}</nav>'
            f'<div class="meta">fork <b>{E(config.FORK)}</b> &middot; EL &middot; newest EELS release {a(snap["release_url"], snap["newest_release"])}<br>'
            f'snapshot {E(snap["taken_at"])} &middot; {a(snap["listing_url"], "hive listing")} ({snap["listing_rows"]} runs)</div></header>'
            f'<main>{fallback_banner(snap)}{stale_banner(snap)}{body}</main><aside id="d" role="dialog" aria-label="Cell evidence"><div id="dc"></div></aside><script>{JS}</script></body></html>')


def cells_for(snap, attestations):
    cells = []
    for eip in tested(snap):
        for client in config.CLIENTS:
            cell = chain(eip, client, snap, attestations)
            cell["links"]["_dir"] = snap["eips"][eip]["test_dir"].rsplit("/", 1)[-1]
            cells.append(cell)
    return cells


def cell_sub(cell):
    r = cell["links"]["run"]
    if cell["headline"] == "stale-release":
        return f"old {r['passed']}/{r['total']} &middot; newest {E(release_short(r['newest_release']))}"
    if cell["headline"] == "open":
        return f"run {r['passed']}/{r['total']} &middot; next: prove"
    if r.get("image"):
        return E(r["image"].rsplit(":", 1)[-1].replace("-linux-amd64", ""))
    return ""


def matrix_html(snap, cells):
    by = {(c["eip"], c["client"]): c for c in cells}
    head = "<tr><th></th>" + "".join(f"<th>{a_local(client_href(c), config.CLIENT_LABEL[c])}<br><small class=muted>{E(release_short(snap['runs'][c]['release']) if c in snap['runs'] else '-')}</small></th>" for c in config.CLIENTS) + "</tr>"
    head += ('<tr class="counts"><th class="row"><small>cells by weakest check</small></th>'
             + "".join(f'<th><small>{counts_html([c for c in cells if c["client"] == cl])}</small></th>' for cl in config.CLIENTS) + "</tr>")
    rows, templates = [], []
    for eip in index.row_order(snap["eips"]):
        info = snap["eips"][eip]
        if not info.get("test_dir"):
            rows.append(f'<tr class="nt" id="r-{eip}"><th class="row">{a_local(eip_href(eip), "EIP-" + eip)}<small>{E(eip_name(info))}</small>{stage_html(info, snap)}</th>'
                        f'<td class="c none" colspan="{len(config.CLIENTS)}" data-mark="no-tests"><div class="hl">no tests yet</div><div class="sub">{E(no_tests_text(info, snap))}</div></td></tr>')
            continue
        badge = f'<div class="badge" title="EIP text changed after the version EELS implements">{len(info["deltas"])} spec change(s) since EELS</div>' if info["deltas"] else ""
        pend = f'<div class="badge" style="background:#1f2937;color:#8b95a7" title="open EIP PRs, not spec yet">{len(info["pending"])} open PR(s), not counted</div>' if info["pending"] else ""
        tr = [f'<th class="row">{a_local(eip_href(eip), "EIP-" + eip)}<small>{E(eip_name(info))}</small>{stage_html(info, snap)}{badge}{pend}</th>']
        for client in config.CLIENTS:
            c = by[(eip, client)]
            cid = f"{eip}-{client}"
            tr.append(f'<td class="c {STATE_CLASS[c["headline"]]}" id="c-{cid}" tabindex="0" role="button" onclick="openD(\'{cid}\',this)">{dots(c)}<div class="hl">{E(headline_text(c))}</div><div class="sub">{cell_sub(c)}</div></td>')
            templates.append(f'<template id="t-{cid}">{drawer(c, snap)}</template>')
        rows.append("<tr>" + "".join(tr) + "</tr>")
    strip = ""
    wide = {c: r["client_wide_failures"] for c, r in snap["runs"].items() if r["client_wide_failures"] and r["release"] == snap["newest_release"]}
    if wide:
        strip = '<div class="strip">client-wide failures outside EIP dirs (not counted in cells): ' + " &middot; ".join(
            f'{E(config.CLIENT_LABEL[c])} {len(v)}' for c, v in wide.items()) + "</div>"
    legend = ('<div class="legend">A cell shows its weakest check. The three dots are: <b>spec change</b> &middot; <b>test proof</b> &middot; <b>client run</b>.'
              '<i class="dot ok"></i>ok<i class="dot warn"></i>spec change untested<i class="dot stale"></i>old tests, re-run<i class="dot bad"></i>fails<i class="dot"></i>no data</div>')
    cov = coverage_html(snap) if snap.get("meta") else ""
    return strip + cov + f'<div class="wrap"><table class="m">{head}{"".join(rows)}</table></div>' + legend + "".join(templates)


def queue_html(snap, cells):
    items = queue(cells, tested(snap))
    out = ['<h2 style="margin:4px 0 12px">Work queue <span class="muted" style="font-size:14px;font-weight:400">each item is one next action</span></h2>']
    for i, it in enumerate(items, 1):
        clients = ", ".join(config.CLIENT_LABEL[c] for c in it["clients"])
        if it["kind"] == "open-delta":
            info = snap["eips"][it["eip"]]
            delta = next(d for d in info["deltas"] if d["commit"] == it["commit"])
            cands = "".join(f'<div class="cand"><code>{E(t)}</code> <em>passes on: {", ".join(f"{config.CLIENT_LABEL[c]} {p}/{n}" for c, (p, n) in v.items())}</em></div>' for t, v in it["candidates"].items())
            body = (f'<span class="k warn">EIP-{it["eip"]} &middot; spec change untested</span> {a(gh(config.EIPS_REPO, "commit", it["commit"]), it["commit"][:8])} {E(delta["subject"])}'
                    f'<div class="muted">affects {E(clients)}</div>{constants_html(delta)}{cands}')
        elif it["kind"] == "run-fail":
            body = (f'<span class="k bad">EIP-{it["eip"]} &middot; fail</span> {E(clients)}: {len(it["failed"])} failing'
                    + "".join(f'<div><code>{E(short_test(f))}</code></div>' for f in it["failed"][:3]))
        else:
            body = f'<span class="k stale">EIP-{it["eip"]} &middot; old tests</span> {E(clients)} last ran {E(release_short(it["release"]))}'
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
    for sub in ("eip", "client"):
        os.makedirs(os.path.join(out_dir, "api", sub), exist_ok=True)
    rows = feed_rows(snap, attestations)
    with open(os.path.join(out_dir, "changes.html"), "w") as f:
        f.write(page(f"{config.NAME} · spec changes", "changes", feed_html(snap, rows), snap))
    with open(os.path.join(out_dir, "api", "changes.json"), "w") as f:
        json.dump({"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "changes": rows}, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "api", "eips.json"), "w") as f:
        json.dump(eips_doc(snap), f, indent=1, sort_keys=True)
    for eip in index.row_order(snap["eips"]):
        with open(os.path.join(out_dir, eip_href(eip)), "w") as f:
            f.write(page(f"{config.NAME} · EIP-{eip}", "", eip_page_html(eip, snap, cells, attestations), snap))
        info = snap["eips"][eip]
        if not info.get("test_dir"):
            continue
        write_json(os.path.join(out_dir, "api", "eip", f"{eip}.json"), snap, [c for c in cells if c["eip"] == eip],
                   [it for it in items if it["eip"] == eip],
                   {"title": info.get("title"), "status": info.get("status"), "stage": info.get("stage"), "meta": snap.get("meta"),
                    "constants": {d["commit"]: d.get("constants", []) for d in info["deltas"]}})
    for client in config.CLIENTS:
        with open(os.path.join(out_dir, client_href(client)), "w") as f:
            f.write(page(f"{config.NAME} · {config.CLIENT_LABEL[client]}", "", client_page_html(client, snap, cells, items), snap))
        write_json(os.path.join(out_dir, "api", "client", f"{client}.json"), snap, [c for c in cells if c["client"] == client],
                   [it for it in items if client in it["clients"]])
    return cells, items


def eips_doc(snap):
    rows = []
    for eip in index.row_order(snap["eips"]):
        info = snap["eips"][eip]
        rows.append({"eip": eip, "title": info.get("title"), "status": info.get("status"), "category": info.get("category"),
                     "stage": info.get("stage") or [], "test_dir": info.get("test_dir"), "checked": info.get("checked"),
                     "behind": len(info["deltas"]) if info.get("pin") else None, "page": f'{config.SITE_URL}/{eip_href(eip)}'})
    return {"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "newest_release": snap["newest_release"],
            "meta": snap.get("meta"), "eips": rows}


def write_json(path, snap, cells, items, spec=None):
    doc = {"fork": config.FORK, "snapshot": snap["taken_at"], "source": snap.get("source", "live"), "newest_release": snap["newest_release"], "listing_url": snap["listing_url"],
           "cells": [{"eip": c["eip"], "client": c["client"], "headline": c["headline"], "text": headline_text(c), "why": why(c, snap),
                      "links": {k: v for k, v in c["links"].items() if not k.startswith("_")}} for c in cells],
           "todo": items}
    if spec is not None:
        doc["spec"] = spec
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True, default=str)
