# p2ked quality checks.
#
# Every target works on the virtualenv in .venv, created by `make install`.
# If .venv is absent the Python targets fall back to the interpreter on
# PATH, so the file is still usable on a machine set up some other way.
#
# Run `make check` before pushing. It is what CI would run, and it fails
# on the first error.

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV := .venv

# Resolved with `=` (lazy), not `:=` (immediate), on purpose. `make install`
# creates .venv, so a parse-time check for it would always miss and every
# target would silently fall back to the host interpreter -- which is what
# happened the first time this ran.
#
# Windows keeps its console scripts in .venv/Scripts, everything else in
# .venv/bin, so the layout cannot be assumed POSIX: CI runs this same file
# on Linux, macOS and Windows.
VENV_BIN = $(shell [ -d "$(VENV)/Scripts" ] && echo "$(VENV)/Scripts" || ([ -d "$(VENV)/bin" ] && echo "$(VENV)/bin"))

# The venv's interpreter, for the `install` target below. Lazy for the same
# reason `VENV_BIN` is: the first recipe line creates the venv, and only
# the lines after it may assume the directory is there.
VENV_PYTHON = $(if $(VENV_BIN),$(VENV_BIN)/python,python3)

# A tool from .venv when it is there, otherwise the one on PATH.
tool = $(if $(VENV_BIN),$(VENV_BIN)/$(1),$(1))

RUFF           := $(call tool,ruff)
MYPY           := $(call tool,mypy)
PYTEST         := $(call tool,pytest)
PIP_AUDIT      := $(call tool,pip-audit)
VULTURE        := $(call tool,vulture)
DEPTRY         := $(call tool,deptry)
DETECT_SECRETS := $(call tool,detect-secrets)
PRE_COMMIT     := $(call tool,pre-commit)
P              := $(call tool,python)

SRC       := p2k p2ked
SRC_ALL   := p2k p2ked tools tests
PYPROJECT := pyproject.toml
BASELINE  := .secrets.baseline

## ---------------------------------------------------------------- help ---

.PHONY: help
help: ## Show this help
	@echo "p2ked development checks"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sort \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Start with:  make install && make check"

## ------------------------------------------------------------- install ---

.PHONY: install
install: ## Create .venv and install pinned dev dependencies
	python3 -m venv $(VENV)
	@# Explicit $(VENV_PYTHON), not $(P): $(P) is resolved against the
	@# venv's existence, which is false until the line above has run --
	@# and a literal `.venv/bin/python` does not exist on Windows, where
	@# the interpreter lives in `.venv/Scripts`.
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements-dev.txt
	@# --no-deps used to be here, and is gone now that vinsynlib resolves
	@# from an index: with it, the shared library -- a runtime dependency
	@# p2ked cannot start without -- was never installed at all, and
	@# `make install && make check` failed on the first import. The pinned
	@# dev set is installed above, so this line adds the project and the
	@# runtime dependencies the pins do not cover.
	$(VENV_PYTHON) -m pip install -e .
	@echo
	@echo "Done. Next: make install-hooks"

.PHONY: install-hooks
install-hooks: ## Install the pre-commit hooks into .git/hooks
	$(PRE_COMMIT) install

## ---------------------------------------------------------------- lint ---

.PHONY: lint
lint: ## ruff check (lint rules only; see make format)
	$(RUFF) check --no-cache $(SRC_ALL) $(PYPROJECT)

.PHONY: format
format: ## ruff format -- rewrites files in place
	$(RUFF) format $(SRC_ALL) $(PYPROJECT)

.PHONY: format-check
format-check: ## ruff format --check
	$(RUFF) format --check --diff $(SRC_ALL) $(PYPROJECT)

# ---------------------------------------------------------------- checks ---

.PHONY: typecheck
typecheck: ## mypy
	$(MYPY)

.PHONY: test
test: ## pytest, fast, no coverage
	$(PYTEST) -q

.PHONY: coverage
coverage: ## pytest with a term-missing report, enforcing fail_under
	@# One --cov per package. "--cov=p2k p2ked" makes pytest treat p2ked
	@# as a test path (no tests ran); "--cov=p2k,p2ked" is read as a
	@# single module literally named "p2k,p2ked" (never imported).
	@# fail_under lives in [tool.coverage.report], so `make check` and a
	@# bare `pytest --cov` agree on it.
	$(PYTEST) --cov=p2k --cov=p2ked --cov-report=term-missing -q

# --- hardware ----------------------------------------------------------------

# The hardware suite is a separate target, not part of `check`: CLAUDE.md's
# rule is that only one session drives a unit at a time, and CI -- which
# runs `make check` -- must not be it. `--hardware` and P2KED_HARDWARE=1 open
# the ports; without them every test in the file skips with a reason.
#
# `-o addopts=""` because the ordinary addopts carry --cov with a fail_under
# gate: a hardware-only run measures coverage over the handful of tests that
# just ran and would fail by construction. `-rs -s` so the findings the
# probe prints are actually seen -- a skip reason and a list of answered
# parameter IDs are the output of this target.
.PHONY: test-hardware
test-hardware: ## tests that need a real Proteus 2000 (opens MIDI ports)
	$(PYTEST) tests/test_hardware.py --hardware -o addopts="" -p no:cacheprovider -rs -s

# ----------------------------------------------------------------- audit ---

.PHONY: audit
audit: audit-vulns audit-deadcode audit-deps audit-secrets ## All static audits

.PHONY: audit-vulns
audit-vulns: ## pip-audit against the pinned dependency set
# vinsynlib is an index dependency now (it is on PyPI), so it is audited with
# the rest. It used to be filtered out, because as a sibling checkout pip
# could not resolve it and pip-audit would fail resolving rather than audit
# anything. The pinned toolchain below is audited in full.
	@$(P) -c "import pathlib, tomllib; \
	    data = tomllib.load(open('pyproject.toml', 'rb')); \
	    pathlib.Path('.audit-runtime-req.txt').write_text(\
	        ''.join(r + chr(10) for r in data['project']['dependencies']))"
	@$(PIP_AUDIT) --progress-spinner=off -r .audit-runtime-req.txt; \
	    status=$$?; rm -f .audit-runtime-req.txt; exit $$status
	$(PIP_AUDIT) --progress-spinner off --requirement requirements-dev.txt

.PHONY: audit-deadcode
audit-deadcode: ## vulture -- dead code, min-confidence 80
	$(VULTURE) --min-confidence 80 $(SRC_ALL)

.PHONY: audit-deps
audit-deps: ## deptry -- missing, unused and transitive dependencies
	$(DEPTRY) .

.PHONY: audit-secrets
audit-secrets: ## detect-secrets against the generated baseline
	@# Scanned over `git ls-files`, not `--all-files`: detect-secrets 1.5's
	@# --all-files walks the filesystem and would read .venv.
	@git ls-files -z | xargs -0 $(DETECT_SECRETS)-hook --baseline $(BASELINE)

.PHONY: secrets-update
secrets-update: ## Regenerate .secrets.baseline from the tracked files
	@git ls-files -z | xargs -0 $(DETECT_SECRETS) scan > $(BASELINE)
	@echo "wrote $(BASELINE) -- review the diff before committing it"

## ----------------------------------------------------------------- all ---

# `coverage` rather than `test`: it runs the whole suite anyway, and using
# it here is what makes the fail_under gate part of `make check` without
# running the tests twice.
.PHONY: check
check: lint format-check typecheck coverage audit ## Everything. Fails on the first error.
	@echo
	@echo "OK: lint, typecheck, tests and audits all passed."

.PHONY: ci
ci: check ## Alias for check, for a CI job.

# --------------------------------------------------------------- hygiene ---

.PHONY: pre-commit-run
pre-commit-run: ## Run every pre-commit hook against all tracked files
	$(PRE_COMMIT) run --all-files

.PHONY: clean
clean: ## Remove caches and coverage output
	rm -rf .pytest_cache .coverage .mypy_cache .ruff_cache htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +