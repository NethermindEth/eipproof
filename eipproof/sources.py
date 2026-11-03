import json
import os
import subprocess
import urllib.request

from . import config

CACHE = os.environ.get("EIPPROOF_CACHE", os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache"))
UA = {"User-Agent": f"{config.NAME}/0.1"}


def git(repo, *args):
    return subprocess.run(["git", f"--git-dir={repo}", *args], check=True, capture_output=True, text=True).stdout


def ensure_repo(name, slug, refspec):
    path = os.path.join(CACHE, name)
    if not os.path.isdir(path):
        subprocess.run(["git", "init", "--quiet", "--bare", path], check=True)
        git(path, "config", "remote.origin.url", f"{config.GITHUB}/{slug}.git")
        git(path, "config", "remote.origin.promisor", "true")
        git(path, "config", "remote.origin.partialclonefilter", "blob:none")
    git(path, "fetch", "--quiet", "--force", "--filter=blob:none", f"{config.GITHUB}/{slug}.git", refspec)
    return path


def http_get(url, byte_range=None):
    headers = dict(UA)
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=600) as r:
        return r.read()


def hive_listing():
    raw = http_get(f"{config.HIVE}/listing.jsonl").decode()
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def hive_result_path(file_name):
    os.makedirs(os.path.join(CACHE, "hive"), exist_ok=True)
    path = os.path.join(CACHE, "hive", file_name)
    if not os.path.exists(path):
        tmp = path + ".part"
        with urllib.request.urlopen(urllib.request.Request(f"{config.HIVE}/results/{file_name}", headers=UA), timeout=1800) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        os.rename(tmp, path)
    return path


def hive_simlog_head(sim_log):
    return http_get(f"{config.HIVE}/results/{sim_log}", (0, 65535)).decode(errors="replace")


def gh_api(path):
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)
