PYTHON ?= python3

.PHONY: help test compile pipeline semantic clean

help:
	@echo "Kritva Forge targets:"
	@echo "  make test       - run unit tests"
	@echo "  make compile    - syntax-check Python sources"
	@echo "  make pipeline   - run RTL pipeline (DATA_DIR and OUT_DIR configurable)"
	@echo "  make semantic   - run semantic analysis (PROJECT configurable)"

compile:
	$(PYTHON) -m compileall -q scripts tests

test:
	$(PYTHON) -m pytest -q

DATA_DIR ?= data/raw_rtl
OUT_DIR ?= out
pipeline:
	PYTHONPATH=. $(PYTHON) -m scripts.pipeline.run_pipeline $(DATA_DIR) $(OUT_DIR)

PROJECT ?= $(OUT_DIR)
semantic:
	PYTHONPATH=. $(PYTHON) -m scripts.pipeline.run_semantic $(PROJECT)

clean:
	rm -rf __pycache__ scripts/**/__pycache__ tests/**/__pycache__ .pytest_cache out
