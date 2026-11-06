import os
import re
import subprocess
import sys

import pytest

from eipproof import cli

ROOT = cli.ROOT


def run(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def make_targets():
    text = open(os.path.join(ROOT, "Makefile")).read()
    return set(re.findall(r"^([a-z][a-z-]*):", text, re.M))


def test_make_help_describes_every_target():
    out = run("make", "help").stdout
    for target in make_targets() - {"help"}:
        assert re.search(rf"^make {target}\s+\S", out, re.M), target


def test_make_help_is_the_default_target():
    assert run("make").stdout == run("make", "help").stdout


def test_readme_lists_every_make_target():
    readme = open(os.path.join(ROOT, "README.md")).read()
    for target in make_targets() - {"help"}:
        assert f"make {target}" in readme, target


def test_cli_help_describes_every_command():
    out = run(sys.executable, "-m", "eipproof.cli", "--help").stdout
    for command in ("build", "why", "prove", "pr-impact"):
        assert re.search(rf"^\s+{command}\s+\S", out, re.M), command


def test_why_on_an_unknown_eip_names_the_tracked_ones(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["why", "9999", "nethermind"])
    assert "EIP-9999" in str(e.value)
    assert "8141" in str(e.value)
