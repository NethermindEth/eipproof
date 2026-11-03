PY ?= .venv/bin/python
PORT ?= 8765

.PHONY: venv test build offline serve

venv:
	test -x $(PY) || (uv venv -q .venv && uv pip install -q --python $(PY) pytest pyyaml)

test: venv
	$(PY) -m pytest -q tests

build: venv
	$(PY) -m eipproof.cli build

offline: venv
	$(PY) -m eipproof.cli build --offline

serve:
	cd site && python3 -m http.server $(PORT)
