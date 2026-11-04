import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import date

from . import config

ENGINE_FORMAT = "blockchain_test_engine"


def case_ids(junit_path):
    out = {}
    for tc in ET.parse(junit_path).iter("testcase"):
        if tc.find("skipped") is not None:
            continue
        path = tc.get("classname", "").replace(".", "/") + ".py"
        name = tc.get("name", "").split("@t8n-cache-", 1)[0]
        params = name[name.find("[") + 1:-1].split("-") if "[" in name else []
        if not any(p.startswith(ENGINE_FORMAT) for p in params):
            continue
        failed = tc.find("failure") is not None or tc.find("error") is not None
        out[f"{path}::{name}"] = not failed
    return out


def fill(eels, tests, workers):
    tmp = tempfile.mkdtemp(prefix="eipproof-fill-")
    junit = os.path.join(tmp, "junit.xml")
    cmd = ["uv", "run", "fill", tests, "--fork", config.FILL_FORK, "--output", os.path.join(tmp, "out"),
           "--clean", "-q", f"--junitxml={junit}"]
    if workers > 1:
        cmd += ["-n", str(workers)]
    subprocess.run(cmd, cwd=eels, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    try:
        return case_ids(junit)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def git(eels, *args):
    return subprocess.run(["git", *args], cwd=eels, check=True, capture_output=True, text=True).stdout.strip()


def killed(baseline, mutant):
    return sorted(t for t, ok in baseline.items() if ok and mutant.get(t) is False)


def differential(eels, tests, patch, workers=1):
    if git(eels, "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"{eels} has local changes; clean it first")
    baseline = fill(eels, tests, workers)
    git(eels, "apply", os.path.abspath(patch))
    try:
        mutant = fill(eels, tests, workers)
    finally:
        git(eels, "apply", "-R", os.path.abspath(patch))
    return baseline, mutant


def proof_doc(eip, commit, eels, tests, patch_name, baseline, mutant, workers):
    head = git(eels, "rev-parse", "HEAD")
    ref = git(eels, "describe", "--tags", "--exact-match", "HEAD") if _tagged(eels) else head
    return {
        "eip": eip,
        "commit": commit,
        "kind": "normative",
        "fork": config.FORK,
        "eels": {"repo": config.EELS_REPO, "ref": ref, "commit": head},
        "tests": tests,
        "mutant": patch_name,
        "baseline": {"cases": len(baseline), "passed": sum(baseline.values())},
        "with_mutant": {"cases": len(mutant), "passed": sum(mutant.values())},
        "killed": killed(baseline, mutant),
        "command": f"python -m eipproof.cli prove {eip} {commit} --fork {config.FORK} --eels <execution-specs at {ref}> "
                   f"--tests {tests} --mutant proofs/{patch_name}" + (f" -n {workers}" if workers > 1 else ""),
        "date": date.today().isoformat(),
    }


def _tagged(eels):
    return subprocess.run(["git", "describe", "--tags", "--exact-match", "HEAD"], cwd=eels,
                          capture_output=True).returncode == 0


def editorial_doc(eip, commit, reason):
    return {"eip": eip, "commit": commit, "kind": "editorial", "reason": reason, "killed": [],
            "date": date.today().isoformat()}
