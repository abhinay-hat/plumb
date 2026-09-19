.PHONY: dev test demo eval build

PYTHON ?= .venv/bin/python

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
