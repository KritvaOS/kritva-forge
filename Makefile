# =============================================================================
# Copyright (c) 2026 KritvaOS
# SPDX-License-Identifier: Apache-2.0
#
# File        : Makefile
# Description : Build, test, and development targets for Kritva Forge
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

DATA_DIR ?= data/raw_rtl
OUT_DIR ?= out
PROJECT ?= $(OUT_DIR)

.PHONY: help venv setup test compile pipeline semantic clean

help:
	@echo "Kritva Forge targets:"
	@echo "  make setup      - create .venv and install Python dependencies"
	@echo "  make test       - run unit tests"
	@echo "  make compile    - syntax-check Python sources"
	@echo "  make pipeline   - run RTL pipeline (DATA_DIR and OUT_DIR configurable)"
	@echo "  make semantic   - run semantic analysis (PROJECT configurable)"
	@echo "  make clean      - remove generated Python/test/pipeline output"
	@echo ""
	@echo "Environment:"
	@echo "  VENV=<path>     - Python virtual environment (default: .venv)"
	@echo "  PYTHON=<path>   - Python interpreter (default: .venv/bin/python)"
	@echo "  DATA_DIR=<path> - RTL input directory (default: data/raw_rtl)"
	@echo "  OUT_DIR=<path>  - pipeline output directory (default: out)"
	@echo "  PROJECT=<path>  - semantic-analysis project (default: out)"

venv:
	@if [ ! -x "$(PYTHON)" ]; then \
		echo "[INFO] Creating Python virtual environment: $(VENV)"; \
		python3 -m venv "$(VENV)"; \
	else \
		echo "[INFO] Python virtual environment already exists: $(VENV)"; \
	fi

setup: venv
	@echo "[INFO] Installing Kritva Forge Python dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

compile: setup
	$(PYTHON) -m compileall -q scripts tests

test: setup
	$(PYTHON) -m pytest -q

pipeline: setup
	PYTHONPATH=. $(PYTHON) -m scripts.pipeline.run_pipeline $(DATA_DIR) $(OUT_DIR)

semantic: setup
	PYTHONPATH=. $(PYTHON) -m scripts.pipeline.run_semantic $(PROJECT)

clean:
	rm -rf __pycache__ scripts/**/__pycache__ tests/**/__pycache__ .pytest_cache out

