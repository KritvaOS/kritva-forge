# Migration Notes: bes_verilog_llm → Kritva Forge

## Source

This repository was created from the supplied `bes_verilog_llm` archive.
Only canonical files from the archive were migrated. Numbered historical copies from the surrounding upload set were intentionally not copied.

## Deliberately excluded

- Generated RTL/YAML/dataset data
- Model checkpoints and local environments
- Log files
- Temporary/generated output
- Legacy duplicate parser tree `scripts/rtl_parser/`
- Legacy `scripts/rtl_parser.py`
- Legacy orchestration references to scripts that were not present in the supplied archive

## New layout

- `scripts/parser/` — RTL parsing
- `scripts/rtl_ir/` — normalized RTL IR
- `scripts/semantic/` — semantic analysis
- `scripts/structural/` — structural analysis
- `scripts/fsm/` — FSM analysis
- `scripts/analysis/` — reports and analysis utilities
- `scripts/dataset/` — dataset generation
- `scripts/pipeline/` — orchestration
- `scripts/debug/` — diagnostics
- `scripts/core/` — shared infrastructure
- `tests/` — reorganized tests
- `data/` — reserved for the private `kritva-forge-data` submodule

## Import cleanup

Project imports were converted to the new `scripts.*` package hierarchy so the repository can be run from its root with `PYTHONPATH=.`.

## Validation

- Python `compileall`: passed
- Semantic unit tests: **43 passed**
- Full test collection requires the external `pyslang` dependency; the supplied runtime did not have it installed.

## Known source gap inherited from the archive

`semantic/type_enrichment.py` imports `scripts.semantic.type_info`, but `type_info.py` was not present in the supplied `bes_verilog_llm` archive. This has intentionally not been fabricated during migration. The module should be restored/implemented in a separate change before enabling the full semantic pipeline.


## Private Data Repository Migration

The current repository no longer treats `data/raw_rtl`, `data/curated`, or
`out` as canonical runtime locations. Use `kritva-forge-data`:

- `raw/rtl` — RTL input
- `normalized/ir` — normalized/module YAML artifacts
- `generated/prompts` — generated prompts
- `analysis/reports` — pipeline reports
- `datasets/pipeline` — generated training datasets

The pipeline still accepts the legacy two-positional-argument interface for
compatibility, while the preferred interface uses explicit roots or
`--data-root`.

## KF-DQ-001 — Canonical normalized IR layout

`normalized/ir/<ip>/modules/<module>.yaml` is the only canonical module
representation. Root-level `normalized/ir/<ip>/<module>.yaml` files were stale
`bes_verilog_llm` artifacts and are removed from `kritva-forge-data`.

- `scripts/core/paths.py` provides `iter_module_yamls()`, `iter_ip_dirs()` and
  `find_noncanonical_module_yamls()`; all IR consumers use them.
- FSM report/debug scripts no longer walk the legacy `out/` tree; they take an
  optional `normalized_root` argument (default `<data-root>/normalized/ir`).
- `run_pipeline` never writes prompts/reports/datasets inside
  `normalized_root` and fails if non-canonical module YAMLs are present.
- `make test-data` / `make check-layout` validate a data checkout.
