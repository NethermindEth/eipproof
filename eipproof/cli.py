import argparse
import glob
import json
import os
import sys
from datetime import date

import yaml

from . import build, config, render
from .chain import headline_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_attestations(path=os.path.join(ROOT, "attest")):
    out = []
    for f in sorted(glob.glob(os.path.join(path, "*.yaml"))):
        doc = yaml.safe_load(open(f))
        doc["eip"], doc["file"] = str(doc["eip"]), os.path.basename(f)
        out.append(doc)
    return out


def latest_snapshot():
    snaps = sorted(glob.glob(os.path.join(ROOT, "snapshots", "*.json")))
    if not snaps:
        sys.exit("no snapshot: run `eipproof build` first")
    return snaps[-1]


def cmd_build(args):
    snap_dir = os.path.join(ROOT, "snapshots")
    if args.offline:
        path = latest_snapshot()
    else:
        path = build.write_snapshot(build.snapshot(snap_dir), snap_dir)
    print(f"snapshot {path}")
    snap = build.load_snapshot(path)
    cells, items = render.site(snap, load_attestations(), os.path.join(ROOT, "site"))
    with open(os.path.join(ROOT, "site", "receipts.jsonl"), "w") as f:
        for c in cells:
            f.write(json.dumps({"eip": c["eip"], "client": c["client"], "headline": c["headline"], "text": headline_text(c),
                                "run": {k: v for k, v in c["links"]["run"].items() if k != "failed"}}, sort_keys=True) + "\n")
    with open(os.path.join(ROOT, "site", "queue.jsonl"), "w") as f:
        for it in items:
            f.write(json.dumps(it, sort_keys=True) + "\n")
    width = max(len(config.CLIENT_LABEL[c]) for c in config.CLIENTS)
    print("EIP     " + "  ".join(f"{config.CLIENT_LABEL[c]:<22}" for c in config.CLIENTS))
    by = {(c["eip"], c["client"]): c for c in cells}
    for eip in config.ROW_ORDER:
        if (eip, config.CLIENTS[0]) in by:
            print(f"{eip:<8}" + "  ".join(f"{headline_text(by[(eip, c)]):<22}" for c in config.CLIENTS))
    print(f"site {os.path.join(ROOT, 'site')}/index.html  ({len(cells)} cells, {len(items)} queue items)")


def cmd_why(args):
    snap = build.load_snapshot(latest_snapshot())
    cell = next(c for c in render.cells_for(snap, load_attestations()) if c["eip"] == args.eip and c["client"] == args.client)
    print(f"EIP-{args.eip} x {config.CLIENT_LABEL[args.client]}: {headline_text(cell)}")
    print(render.why(cell, snap))
    for key in ("spec", "test", "run"):
        print(f"  {key:<5} {cell['links'][key]['state']}")


def cmd_attest(args):
    os.makedirs(os.path.join(ROOT, "attest"), exist_ok=True)
    path = os.path.join(ROOT, "attest", f"{args.eip}-{args.commit[:8]}.yaml")
    doc = {"eip": args.eip, "commit": args.commit, "tests": args.tests.split(","), "author": args.author,
           "date": date.today().isoformat(), "kind": args.kind, "note": args.note}
    with open(path, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False)
    print(path)


def main(argv=None):
    p = argparse.ArgumentParser(prog=config.NAME)
    sub = p.add_subparsers(required=True)
    b = sub.add_parser("build")
    b.add_argument("--offline", action="store_true")
    b.set_defaults(fn=cmd_build)
    w = sub.add_parser("why")
    w.add_argument("eip")
    w.add_argument("client", choices=config.CLIENTS)
    w.set_defaults(fn=cmd_why)
    t = sub.add_parser("attest")
    t.add_argument("eip")
    t.add_argument("commit")
    t.add_argument("--tests", required=True)
    t.add_argument("--author", required=True)
    t.add_argument("--kind", choices=["normative", "editorial"], default="normative")
    t.add_argument("--note", default="")
    t.set_defaults(fn=cmd_attest)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
