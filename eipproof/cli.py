import argparse
import glob
import json
import os
import shutil
import sys

import yaml

from . import build, config, health, prove, render
from .chain import headline_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_proofs(path=os.path.join(ROOT, "proofs")):
    out = []
    for f in sorted(glob.glob(os.path.join(path, "*.yaml"))):
        doc = yaml.safe_load(open(f))
        doc["eip"], doc["file"] = str(doc["eip"]), os.path.basename(f)
        out.append(doc)
    return out


def snap_dir():
    return os.path.join(ROOT, "snapshots", config.SUBDIR)


def latest_snapshot():
    snaps = sorted(glob.glob(os.path.join(snap_dir(), "*.json")))
    if not snaps:
        sys.exit("no snapshot: run `eipproof build` first")
    return snaps[-1]


def write_site(snap, out_dir):
    cells, items = render.site(snap, load_proofs(), out_dir)
    with open(os.path.join(out_dir, "receipts.jsonl"), "w") as f:
        for c in cells:
            f.write(json.dumps({"eip": c["eip"], "client": c["client"], "headline": c["headline"], "text": headline_text(c),
                                "run": {k: v for k, v in c["links"]["run"].items() if k != "failed"}}, sort_keys=True) + "\n")
    with open(os.path.join(out_dir, "queue.jsonl"), "w") as f:
        for it in items:
            f.write(json.dumps(it, sort_keys=True) + "\n")
    return cells, items


def cmd_build(args):
    for fork in args.fork or list(config.FORKS):
        config.use(fork)
        build_fork(args)
    config.use(config.DEFAULT_FORK)


def build_fork(args):
    if args.offline:
        path = latest_snapshot()
    else:
        path = build.write_snapshot(build.snapshot(snap_dir()), snap_dir())
    print(f"fork {config.FORK}  snapshot {path}")
    snap = build.load_snapshot(path)
    snap["source"] = "snapshot" if args.offline else "live"
    out_dir = os.path.join(ROOT, "site", config.SUBDIR)
    cells, items = write_site(snap, out_dir)
    prev = "/".join(p for p in (args.prev_site, config.SUBDIR, "api/status.json") if p) if args.prev_site else None
    failures = health.live_failures(health.fetch_status(prev), args.live_failed)
    doc = health.status_doc(snap, len(cells), failures, health.head_commit(ROOT))
    with open(os.path.join(out_dir, "api", "status.json"), "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
    print(f"source {doc['source']}  live_failures {failures}")
    width = max(len(config.CLIENT_LABEL[c]) for c in config.CLIENTS)
    print("EIP     " + "  ".join(f"{config.CLIENT_LABEL[c]:<22}" for c in config.CLIENTS))
    by = {(c["eip"], c["client"]): c for c in cells}
    for eip in render.tested(snap):
        print(f"{eip:<8}" + "  ".join(f"{headline_text(by[(eip, c)]):<22}" for c in config.CLIENTS))
    for eip in render.untested(snap):
        print(f"{eip:<8}" + render.no_tests_text(snap["eips"][eip], snap))
    print(f"site {out_dir}/index.html  ({len(cells)} cells, {len(items)} queue items)")


def cmd_why(args):
    config.use(args.fork)
    snap = build.load_snapshot(latest_snapshot())
    cell = next(c for c in render.cells_for(snap, load_proofs()) if c["eip"] == args.eip and c["client"] == args.client)
    print(f"EIP-{args.eip} x {config.CLIENT_LABEL[args.client]}: {headline_text(cell)}")
    print(render.why(cell, snap))
    for key in ("spec", "test", "run"):
        print(f"  {render.DOT[key]:<12} {render.LABEL.get(cell['links'][key]['state'], cell['links'][key]['state'])}")


def cmd_prove(args):
    out_dir = os.path.join(ROOT, "proofs")
    os.makedirs(out_dir, exist_ok=True)
    stem = f"{args.eip}-{args.commit[:8]}"
    if args.editorial:
        doc = prove.editorial_doc(args.eip, args.commit[:8], args.editorial)
    else:
        if not (args.eels and args.tests and args.mutant):
            sys.exit("prove needs --eels, --tests and --mutant, or --editorial REASON")
        patch_name = f"{stem}.patch"
        if os.path.abspath(args.mutant) != os.path.join(out_dir, patch_name):
            shutil.copyfile(args.mutant, os.path.join(out_dir, patch_name))
        baseline, mutant = prove.differential(args.eels, args.tests, args.mutant, args.workers)
        doc = prove.proof_doc(args.eip, args.commit[:8], args.eels, args.tests, patch_name, baseline, mutant, args.workers)
    path = os.path.join(out_dir, f"{stem}.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, width=200)
    if doc["kind"] == "normative":
        print(f"baseline {doc['baseline']['passed']}/{doc['baseline']['cases']} pass, "
              f"with mutant {doc['with_mutant']['passed']}/{doc['with_mutant']['cases']} pass, "
              f"{len(doc['killed'])} case(s) flip")
        for t in doc["killed"]:
            print(f"  flips: {t}")
    print(path)


def main(argv=None):
    p = argparse.ArgumentParser(prog=config.NAME)
    sub = p.add_subparsers(required=True)
    b = sub.add_parser("build")
    b.add_argument("--offline", action="store_true")
    b.add_argument("--fork", action="append", choices=list(config.FORKS), help="build only this fork; repeat for more")
    b.add_argument("--prev-site", metavar="URL", help="base URL of the deployed site, to count live failures in a row")
    b.add_argument("--live-failed", action="store_true", help="this build is a fallback after a failed live build")
    b.set_defaults(fn=cmd_build)
    w = sub.add_parser("why")
    w.add_argument("eip")
    w.add_argument("client", choices=config.CLIENTS)
    w.add_argument("--fork", choices=list(config.FORKS), default=config.DEFAULT_FORK)
    w.set_defaults(fn=cmd_why)
    t = sub.add_parser("prove", help="run EELS tests with and without a mutant that undoes one spec change")
    t.add_argument("eip")
    t.add_argument("commit", help="EIPs commit of the spec change")
    t.add_argument("--eels", help="execution-specs checkout at the release tag")
    t.add_argument("--tests", help="test path inside execution-specs")
    t.add_argument("--mutant", help="patch to execution-specs that undoes the change")
    t.add_argument("-n", "--workers", type=int, default=1)
    t.add_argument("--editorial", metavar="REASON", help="the change has no behaviour; record why instead of running")
    t.set_defaults(fn=cmd_prove)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
