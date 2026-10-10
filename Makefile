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

.PHONY: help venv setup test test-data check-layout check-leakage check-provenance check-stale clean-stale check-manifest check-semantic check-behavior behavior check-structural structural check-fsm fsm prompt-v2 check-prompt-v2 check-compat multitask check-multitask data-quality compile pipeline headers git_sync clean reference-init reference-data reference-regression reference-baseline reference-clean

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
	@echo "  make check-semantic - validate the Semantic IR v2 corpus (schema, identities, references)"
	@echo "  make behavior       - regenerate Behavioral Semantics v1 from Semantic IR v2"
	@echo "  make check-behavior - validate the Behavioral Semantics v1 corpus (evidence, consistency)"
	@echo "  make structural     - regenerate Structural Analysis v1 from Semantic IR v2 + Behavioral Semantics v1"
	@echo "  make check-structural - validate the Structural Analysis v1 corpus (references, provenance, leakage)"
	@echo "  make fsm            - regenerate FSM Analysis v2 from Semantic IR v2 + Behavioral Semantics v1 + Structural Analysis v1"
	@echo "  make check-fsm      - validate the FSM Analysis v2 corpus (identities, references, encoding, leakage)"
	@echo "  make prompt-v2       - regenerate Prompt v2 (generated/prompt/v2) from the four analysis layers"
	@echo "  make check-prompt-v2 - validate Prompt v2 (provenance, abstraction, leakage, size, classification, reports)"
	@echo "  make check-compat    - cross-repository version compatibility (forge requirements vs data versions)"
	@echo "  make multitask       - build the multi-task dataset datasets/multitask/v2 (KF-DQ-013)"
	@echo "  make check-multitask - validate the multi-task dataset (schema, registry, split inheritance, re-derivation)"
	@echo "  make data-quality - test-data + layout + leakage + provenance + semantic + behavior + structural + fsm + prompt-v2 + multitask + stale + manifest + compat gates"
	@echo "  make compile     - syntax-check Python sources"
	@echo "  make headers     - validate KritvaOS source headers"
	@echo "  make pipeline    - parse RTL and generate normalized IR/datasets"
	@echo "  make clean       - remove local Python/test caches only"
	@echo "  make git_sync    - sync git repo to main"
	@echo ""
	@echo "Open-source reference corpus (KF-DQ-012.2; no private data needed):"
	@echo "  make reference-init       - check out the pinned reference/sources submodules"
	@echo "  make reference-data       - materialize build/reference/kritva-forge-data from reference/corpus.yaml"
	@echo "  make reference-regression - reference-data + pipeline + data-quality + compare with reference/expected/summary.json"
	@echo "  make reference-baseline   - regenerate reference/expected/summary.json (review the diff in a PR)"
	@echo "  make reference-clean      - remove build/reference"
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

check-semantic: setup
	PYTHONPATH=. $(PYTHON) scripts/semantic_ir/validator.py --check --data-root "$(DATA_ROOT)"

behavior: setup
	PYTHONPATH=. $(PYTHON) scripts/behavior/analyzer.py --write --data-root "$(DATA_ROOT)"

check-behavior: setup
	PYTHONPATH=. $(PYTHON) scripts/behavior/validator.py --check --data-root "$(DATA_ROOT)"

structural: setup
	PYTHONPATH=. $(PYTHON) scripts/structural/analyzer.py --write --data-root "$(DATA_ROOT)"

check-structural: setup
	PYTHONPATH=. $(PYTHON) scripts/structural/validator.py --check --data-root "$(DATA_ROOT)"

fsm: setup
	PYTHONPATH=. $(PYTHON) scripts/fsm/analyzer.py --write --data-root "$(DATA_ROOT)"

check-fsm: setup
	PYTHONPATH=. $(PYTHON) scripts/fsm/validator.py --check --data-root "$(DATA_ROOT)"

prompt-v2: setup
	PYTHONPATH=. $(PYTHON) scripts/prompt_v2/render.py --write --data-root "$(DATA_ROOT)"

check-prompt-v2: setup
	PYTHONPATH=. $(PYTHON) scripts/prompt_v2/validator.py --check --with-classification --reports --data-root "$(DATA_ROOT)"

check-compat: setup
	PYTHONPATH=. $(PYTHON) scripts/core/compat.py --data-root "$(DATA_ROOT)"

multitask: setup
	PYTHONPATH=. $(PYTHON) scripts/multitask/build.py --data-root "$(DATA_ROOT)"

check-multitask: setup
	PYTHONPATH=. $(PYTHON) scripts/multitask/validator.py --check --data-root "$(DATA_ROOT)"

data-quality: test-data check-layout check-leakage check-provenance check-semantic check-behavior check-structural check-fsm check-prompt-v2 check-multitask check-stale check-manifest check-compat

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

# -----------------------------------------------------------------------------
# Open-source reference corpus (KF-DQ-012.2): same entry points, DATA_ROOT = build/reference/kritva-forge-data
# -----------------------------------------------------------------------------
REF_OUT := $(CURDIR)/build/reference
REF_ROOT := $(REF_OUT)/kritva-forge-data
REF_STATE := $(CURDIR)/build/reference_sources_state.json
REF_EXPECTED := reference/expected/summary.json

reference-init:
	git submodule sync -- reference/sources
	git submodule update --init -- reference/sources
	git submodule status -- reference/sources

reference-data: setup
	PYTHONPATH=. $(PYTHON) scripts/reference/materialize.py --out "$(REF_OUT)"

reference-regression: setup
	PYTHONPATH=. $(PYTHON) scripts/reference/materialize.py --state "$(REF_STATE)"
	$(MAKE) --no-print-directory reference-data
	$(MAKE) --no-print-directory pipeline DATA_ROOT="$(REF_ROOT)"
	$(MAKE) --no-print-directory data-quality DATA_ROOT="$(REF_ROOT)"
	PYTHONPATH=. $(PYTHON) scripts/reference/summary.py --data-root "$(REF_ROOT)" --compare "$(REF_EXPECTED)"
	PYTHONPATH=. $(PYTHON) scripts/reference/materialize.py --check-state "$(REF_STATE)"

reference-baseline: setup
	$(MAKE) --no-print-directory reference-data
	$(MAKE) --no-print-directory pipeline DATA_ROOT="$(REF_ROOT)"
	$(MAKE) --no-print-directory data-quality DATA_ROOT="$(REF_ROOT)"
	PYTHONPATH=. $(PYTHON) scripts/reference/summary.py --data-root "$(REF_ROOT)" --write "$(REF_EXPECTED)"

reference-clean:
	rm -rf "$(REF_OUT)" "$(REF_STATE)"

# Sync git repo to back to main
git_sync:
	git switch main
	git pull --ff-only origin main
	git log --oneline -3

clean:
	rm -rf __pycache__ scripts/**/__pycache__ tests/**/__pycache__ .pytest_cache
