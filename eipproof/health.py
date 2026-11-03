import json
import subprocess
import urllib.request
from datetime import datetime, timezone

from . import config


def head_commit(root):
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def fetch_status(url):
    if not url:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"{config.NAME}/0.1"}), timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


def live_failures(prev, live_failed):
    if not live_failed:
        return 0
    return int((prev or {}).get("live_failures", 0)) + 1


def status_doc(snap, cells, failures, commit):
    return {"source": snap.get("source", "live"), "snapshot": snap["taken_at"], "newest_release": snap["newest_release"],
            "cells": cells, "live_failures": failures, "commit": commit,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
