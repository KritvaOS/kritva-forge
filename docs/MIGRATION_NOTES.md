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
