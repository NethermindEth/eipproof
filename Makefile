PY ?= .venv/bin/python
PORT ?= 8765
ARGS ?=

.PHONY: venv test golden check build offline serve

venv:
	uv sync -q --frozen

test: venv
	$(PY) -m pytest -q tests

golden: venv
	UPDATE_GOLDEN=1 $(PY) -m pytest -q tests/test_site.py

check: venv
	$(PY) -m eipproof.sitecheck site

build: venv
	$(PY) -m eipproof.cli build $(ARGS)

offline: venv
	$(PY) -m eipproof.cli build --offline $(ARGS)

serve:
	cd site && python3 -m http.server $(PORT)
