PY ?= .venv/bin/python
PORT ?= 8765
ARGS ?=

.PHONY: help venv test golden check build offline serve site

help:
	@echo "make site      build site/ from the latest snapshot and serve it on http://localhost:$(PORT)"
	@echo "make test      unit, golden and site tests"
	@echo "make golden    rewrite tests/golden/ after an intended output change"
	@echo "make build     fetch public data, write snapshots/ and site/"
	@echo "make offline   rebuild site/ from the latest snapshot, no network"
	@echo "make check     HTML balance and internal links of site/"
	@echo "make serve     serve site/ on http://localhost:$(PORT)"
	@echo "make venv      install the pinned dependencies into .venv with uv"

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

site: offline serve
