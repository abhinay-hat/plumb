.PHONY: setup dev test demo eval build

PYTHON ?= .venv/bin/python

# core.hooksPath is local config, not repo content — a fresh clone gets
# .githooks/ but the hooks stay inert until this runs.
setup:
	git config core.hooksPath .githooks
	@echo "hooks enabled: $$(git config core.hooksPath)"

dev:
	npx --yes concurrently -n api,web -c blue,green \
		"$(PYTHON) -m uvicorn backend.app:app --reload --port 8000" \
		"npm --prefix frontend run dev"

test:
	$(PYTHON) -m pytest -q

demo:
	$(PYTHON) demo.py

eval:
	$(PYTHON) evals/run.py

build:
	npm --prefix frontend run build
