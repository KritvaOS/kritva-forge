# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : Makefile
# Description : Build, test, and data-pipeline targets for Kritva Forge
#
# Component   : Kritva Forge
# Module      : Build Infrastructure
# Layer       : Development Infrastructure
#
# Author      : Kritva Forge Team
# Created     : 02-10-2026
# =============================================================================

VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(PYTHON) -m pip

# The public repository contains code only.  Runtime RTL and generated data
# live in the sibling private repository by default.
DATA_ROOT ?= ../kritva-forge-data
DATA_DIR ?= $(DATA_ROOT)/raw/rtl/original
NORMALIZED_DIR ?= $(DATA_ROOT)/normalized/ir
PROMPT_DIR ?= $(DATA_ROOT)/generated/prompts
REPORT_DIR ?= $(DATA_ROOT)/analysis/reports
DATASET_DIR ?= $(DATA_ROOT)/datasets/pipeline
CURATED_DIR ?=
PROJECT ?= $(NORMALIZED_DIR)

.PHONY: help venv setup test test-data check-layout check-leakage check-provenance check-stale clean-stale check-manifest data-quality compile pipeline headers git_sync clean

help:
	@echo "Kritva Forge targets:"
	@echo "  make setup       - create .venv and install Python dependencies"
	@echo "  make test        - run unit tests"
	@echo "  make test-data   - run data-repository invariant tests (needs DATA_ROOT)"
	@echo "  make check-layout - fail if non-canonical module YAMLs exist in NORMALIZED_DIR"
	@echo "  make check-leakage - fail if dataset splits leak (needs DATA_ROOT)"
	@echo "  make check-provenance - validate the RTL provenance manifest (needs DATA_ROOT)"
	@echo "  make check-stale - fail on stale/orphan/unmanaged generated artifacts (read-only)"
	@echo "  make clean-stale - list stale-artifact cleanup actions (dry run; APPLY=1 executes)"
	@echo "  make check-manifest - validate the canonical data manifest (publication gate)"
	@echo "  make data-quality - test-data + layout + leakage + provenance + stale + manifest gates"
	@echo "  make compile     - syntax-check Python sources"
	@echo "  make headers     - validate KritvaOS source headers"
	@echo "  make pipeline    - parse RTL and generate normalized IR/datasets"
	@echo "  make clean       - remove local Python/test caches only"
	@echo "  make git_sync    - sync git repo to main"
	@echo ""
	@echo "Private data repository:"
	@echo "  DATA_ROOT=<path>       (default: ../kritva-forge-data)"
	@echo "  DATA_DIR=<path>        RTL input (default: DATA_ROOT/raw/rtl/original)"
	@echo "  NORMALIZED_DIR=<path>  normalized IR (default: DATA_ROOT/normalized/ir)"
	@echo "  PROMPT_DIR=<path>      generated prompts (default: DATA_ROOT/generated/prompts)"
	@echo "  REPORT_DIR=<path>      reports (default: DATA_ROOT/analysis/reports)"
	@echo "  DATASET_DIR=<path>     datasets (default: DATA_ROOT/datasets/pipeline)"
	@echo "  CURATED_DIR=<path>     optional curated prompt/RTL root"

venv:
	@if [ ! -x "$(PYTHON)" ]; then 		echo "[INFO] Creating Python virtual environment: $(VENV)"; 		python3 -m venv "$(VENV)"; 	else 		echo "[INFO] Python virtual environment already exists: $(VENV)"; 	fi

setup: venv
	@echo "[INFO] Installing Kritva Forge Python dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

compile: setup
	$(PYTHON) -m compileall -q scripts tests

test: setup
	$(PYTHON) -m pytest -q

test-data: setup
	KRITVA_FORGE_DATA_ROOT="$(DATA_ROOT)" $(PYTHON) -m pytest -q -rx tests/data

check-layout: setup
	PYTHONPATH=. $(PYTHON) -c "import sys; from scripts.pipeline.run_pipeline import check_canonical_layout; check_canonical_layout(sys.argv[1]); print('[INFO] Canonical IR layout OK:', sys.argv[1])" "$(NORMALIZED_DIR)"

check-leakage: setup
	PYTHONPATH=. $(PYTHON) scripts/dataset/leakage.py --data-root "$(DATA_ROOT)"

check-provenance: setup
	PYTHONPATH=. $(PYTHON) scripts/core/provenance.py --check --data-root "$(DATA_ROOT)"

check-stale: setup
	PYTHONPATH=. $(PYTHON) scripts/core/stale_artifacts.py --check --data-root "$(DATA_ROOT)"

clean-stale: setup
	PYTHONPATH=. $(PYTHON) scripts/core/stale_artifacts.py --clean $(if $(APPLY),--apply,) --data-root "$(DATA_ROOT)"

check-manifest: setup
	PYTHONPATH=. $(PYTHON) scripts/core/data_manifest.py --check --data-root "$(DATA_ROOT)"

data-quality: test-data check-layout check-leakage check-provenance check-stale check-manifest

headers:
	python3 scripts/lint/check_source_headers.py --mode tracked --strict
	python3 tests/lint/test_source_headers.py

pipeline: setup
	@echo "[INFO] RTL input      : $(DATA_DIR)"
	@echo "[INFO] Normalized IR  : $(NORMALIZED_DIR)"
	@echo "[INFO] Prompts        : $(PROMPT_DIR)"
	@echo "[INFO] Reports        : $(REPORT_DIR)"
	@echo "[INFO] Datasets       : $(DATASET_DIR)"
	PYTHONPATH=. $(PYTHON) -m scripts.pipeline.run_pipeline 		--rtl-root "$(DATA_DIR)" 		--normalized-root "$(NORMALIZED_DIR)" 		--prompt-root "$(PROMPT_DIR)" 		--reports-root "$(REPORT_DIR)" 		--datasets-root "$(DATASET_DIR)" 		$(if $(CURATED_DIR),--curated-root "$(CURATED_DIR)",)

# Sync git repo to back to main
git_sync:
	git switch main
	git pull --ff-only origin main
	git log --oneline -3

clean:
	rm -rf __pycache__ scripts/**/__pycache__ tests/**/__pycache__ .pytest_cache
