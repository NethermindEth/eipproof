import glob
import json
import os
import shutil

from . import build, config, render

RAW = "https://raw.githubusercontent.com"


def archived(data_dir):
    if not data_dir:
        return []
    paths = glob.glob(os.path.join(data_dir, "snapshots", config.SUBDIR, "*.json"))
    return sorted(paths, reverse=True)


def stamp_of(path):
    return os.path.basename(path)[:-len(".json")]


def same_content(path, snap):
    return build.content_key(json.load(open(path))) == build.content_key(slim(snap))


def slim(snap):
    return json.loads(json.dumps({**snap, "runs": {c: {k: v for k, v in r.items() if k != "results"} for c, r in snap["runs"].items()}}))


def archive(snap, snap_path, data_dir):
    for path in archived(data_dir):
        if same_content(path, snap):
            return path, False
    if snap.get("source") != "live":
        return None, False
    out = os.path.join(data_dir, "snapshots", config.SUBDIR)
    os.makedirs(os.path.join(out, "cases"), exist_ok=True)
    path = os.path.join(out, f"{build.stamp(snap['taken_at'])}.json")
    with open(path, "w") as f:
        json.dump({k: v for k, v in slim(snap).items() if k not in ("source", "asof")}, f, indent=1, sort_keys=True)
    src = os.path.join(os.path.dirname(snap_path), "cases")
    for run in snap["runs"].values():
        name = f"{run['cases_hash']}.txt.gz"
        if not os.path.exists(os.path.join(out, "cases", name)):
            shutil.copyfile(os.path.join(src, name), os.path.join(out, "cases", name))
    return path, True


def entry(snap, href, json_url):
    return {"taken_at": snap["taken_at"], "newest_release": snap["newest_release"], "runs": len(snap["runs"]), "href": href, "json": json_url}


def json_url(path):
    return "/".join(p for p in (RAW, config.SELF_REPO, config.DATA_BRANCH, "snapshots", config.SUBDIR, os.path.basename(path)) if p)


def render_archive(snap, attestations, site_dir):
    out = os.path.join(site_dir, os.path.dirname(build.permalink(snap["taken_at"])))
    render.site({**snap, "source": "archive"}, attestations, out)


def prepare(snap, snap_path, data_dir=None):
    current, added = archive(snap, snap_path, data_dir) if data_dir else (None, False)
    snap["asof"] = build.permalink(json.load(open(current))["taken_at"] if current else snap["taken_at"])
    return current, added


def write(snap, current, attestations, site_dir, data_dir=None):
    entries, rendered = [], 0
    if not current:
        render_archive(snap, attestations, site_dir)
        entries.append(entry(snap, snap["asof"], None))
        rendered = 1
    for path in archived(data_dir):
        if rendered < config.PERMALINKS:
            old = build.load_snapshot(path)
            render_archive(old, attestations, site_dir)
            href, rendered = build.permalink(old["taken_at"]), rendered + 1
        else:
            old, href = json.load(open(path)), None
        entries.append(entry(old, href, json_url(path)))
    with open(os.path.join(site_dir, "history.html"), "w") as f:
        f.write(render.page(f"{config.NAME} · history", "history", render.history_html(entries), snap))
    with open(os.path.join(site_dir, "api", "history.json"), "w") as f:
        json.dump({"fork": config.FORK, "snapshot": snap["taken_at"], "asof": snap["asof"], "snapshots": entries}, f, indent=1, sort_keys=True)
    return entries
