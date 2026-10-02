# Kritva Forge

## Hardware Design Intelligence

Kritva Forge is an open-source hardware design intelligence framework for understanding, analyzing, and learning from RTL designs.

The project provides a structured pipeline for transforming Verilog/SystemVerilog RTL into machine-readable design knowledge, enabling structural analysis, FSM extraction, dependency analysis, dataset generation, and RTL-oriented AI/LLM research.

Kritva Forge is **not** the RTL implementation of Kritva Nexus or Kritva Edge. It is a separate engineering and research framework that can eventually be used to analyze and understand those designs.

---

## Vision

Modern hardware designs contain significant architectural knowledge distributed across RTL source code, hierarchy, signals, processes, state machines, dependencies, and design intent.

Kritva Forge aims to make this knowledge accessible to both engineers and AI systems.

```text
RTL
 │
 ▼
RTL Parsing
 │
 ▼
Normalized RTL IR
 │
 ├──────────────┐
 ▼              ▼
Semantic      Structural
Analysis       Analysis
 │              │
 └──────┬───────┘
        ▼
   FSM Analysis
        │
        ▼
 Dependency / Graph Analysis
        │
        ▼
   Design Knowledge
        │
        ├──────────────┐
        ▼              ▼
 Dataset Generation   RTL AI / LLM
```

---

## Current Scope

Kritva Forge is being developed around the following capabilities:

* Verilog/SystemVerilog RTL parsing
* Normalized RTL Intermediate Representation (IR)
* Module and hierarchy analysis
* Port and signal analysis
* Assignment and process analysis
* Semantic and symbol analysis
* Structural RTL analysis
* FSM candidate detection
* FSM extraction
* State and transition analysis
* FSM quality analysis
* Dependency and graph analysis
* RTL dataset generation
* Golden dataset generation
* RTL AI/LLM experimentation
* Evaluation and regression analysis

---

## Architecture

The core processing flow is:

```text
                    ┌─────────────────┐
                    │   RTL Source    │
                    │ Verilog/SystemV │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   RTL Parser    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    RTL IR       │
                    │ Normalized Data │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │ Semantic │   │Structural│   │ Process  │
        │ Analysis │   │ Analysis │   │ Analysis │
        └────┬─────┘   └────┬─────┘   └────┬─────┘
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                     ┌────────────┐
                     │ FSM Engine │
                     └─────┬──────┘
                           │
                     ┌─────┴─────┐
                     ▼           ▼
                  Graph        Quality
                  Analysis     Analysis
                     │           │
                     └─────┬─────┘
                           ▼
                  ┌─────────────────┐
                  │ Design Knowledge│
                  └────────┬────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
       Dataset Generation          RTL AI / LLM
```

See [`docs/architecture/architecture.md`](docs/architecture/architecture.md) for details.

---

## Repository Structure

```text
kritva-forge/
│
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── Makefile
├── requirements.txt
│
├── docs/
│   └── architecture/
│       └── architecture.md
│
├── scripts/
│   ├── parser/
│   ├── rtl_ir/
│   ├── semantic/
│   ├── structural/
│   ├── fsm/
│   ├── analysis/
│   ├── dataset/
│   ├── evaluation/
│   └── debug/
│
├── tests/
│   ├── parser/
│   ├── rtl_ir/
│   ├── semantic/
│   ├── structural/
│   └── fsm/
│
├── examples/
│   └── rtl/
│
├── schemas/
│   └── rtl_ir/
│
├── configs/
│
└── data/
    └── ...
```

Runtime data lives in a separate private Git repository, checked out next to
this one (`data/` here only holds a README describing it):

```text
KritvaOS/kritva-forge-data
```

The public repository contains the tools and algorithms. The private repository contains RTL corpora, generated datasets, golden data, benchmarks, and other data that should not be publicly distributed.

---

## Data Separation

Kritva Forge intentionally separates source code from data.

```text
Public                                  Private
KritvaOS/kritva-forge  ──── DATA_ROOT ───▶  KritvaOS/kritva-forge-data
(code, tests, docs)     (default: ../kritva-forge-data)
```

```bash
make pipeline                                   # uses ../kritva-forge-data
make pipeline DATA_ROOT=/path/to/kritva-forge-data
```

The private data repository layout:

```text
kritva-forge-data/
├── raw/
│   └── rtl/
│       ├── original/                 # canonical source RTL (read-only input)
│       └── curated/                  # curated RTL for golden workflows
│
├── normalized/
│   ├── ir/                           # canonical normalized IR
│   │   └── <ip>/
│   │       ├── hierarchy.yaml
│   │       ├── summary.yaml
│   │       ├── modules/
│   │       │   └── <module>.yaml     # the only canonical module IR
│   │       └── rtl/                  # RTL copies (location revisited in KF-DQ-006)
│   └── legacy/                       # retained historical IR
│
├── analysis/
│   ├── reports/                      # current pipeline reports
│   └── legacy/
│
├── generated/
│   ├── prompts/<ip>/                 # current pipeline prompts
│   ├── rtl/pipeline/                 # generated/intermediate RTL (not a source)
│   ├── metadata/
│   ├── statistics/
│   └── legacy/
│
├── datasets/
│   ├── pipeline/                     # current train/validation/test outputs
│   ├── source/
│   └── legacy/
│
├── golden/
├── splits/
└── manifests/
```

Code must read module IR only through `scripts.core.paths.iter_module_yamls()`.
Any other `*.yaml` directly under `normalized/ir/<ip>/` is non-canonical; check a
data checkout with `make check-layout` and `make test-data`.

No proprietary or private RTL should be committed to the public repository.

---

## Design Principles

### 1. Parser First

The parser provides a stable normalized representation of RTL.

Downstream components should consume the normalized RTL IR instead of independently parsing source code.

### 2. Separate Parsing from Understanding

Parsing answers:

> What is syntactically present in the RTL?

Analysis answers:

> What does the RTL structure mean?

Therefore parser, semantic analysis, structural analysis, and FSM analysis remain separate layers.

### 3. Reusable RTL IR

The normalized RTL IR is intended to become the common representation used by:

* Structural analysis
* FSM analysis
* Dependency analysis
* Dataset generation
* Verification analysis
* RTL AI/LLM systems

### 4. No Hardcoded FSM Assumptions

FSM detection should be based on structural and semantic evidence rather than naming conventions alone.

Examples such as:

```text
state
next_state
state_reg
state_next
```

may provide hints, but should not be the fundamental detection mechanism.

### 5. YAML/JSON Must Remain Serializable

The persistent IR must contain serializable representations rather than raw parser AST objects.

Transient AST information may be retained internally when required for analysis.

### 6. Public Code / Private Data

Algorithms, parser infrastructure, schemas, tests, and documentation belong in Kritva Forge.

RTL corpora and private datasets belong in `kritva-forge-data`.

---

## Development Status

Kritva Forge is under active development.

The initial implementation is focused on:

1. RTL parsing
2. Normalized RTL IR
3. Semantic analysis
4. Structural analysis
5. FSM extraction
6. FSM transition recovery
7. FSM quality analysis
8. RTL dataset generation
9. RTL AI/LLM experimentation

Interfaces may evolve during early development.

---

## Roadmap

### Phase 1 — RTL Foundation

* [x] RTL parser foundation
* [x] Normalized RTL IR
* [x] Assignment extraction
* [x] Process/always-block extraction
* [x] Case statement extraction
* [x] Symbol information
* [ ] Formal IR schema/versioning
* [ ] Parser regression suite

### Phase 2 — Structural Intelligence

* [x] Structural RTL analysis foundation
* [ ] Signal role analysis
* [ ] Assignment graph
* [ ] Process role classification
* [ ] Dependency graph
* [ ] Improved candidate detection

### Phase 3 — FSM Intelligence

* [x] FSM candidate detection foundation
* [x] State extraction
* [x] Transition extraction
* [x] Action extraction
* [ ] Strict FSM validation
* [ ] State encoding resolution
* [ ] Unreachable-state analysis
* [ ] Dead-end/terminal-state analysis
* [ ] FSM quality scoring
* [ ] FSM visualization

### Phase 4 — Dataset Intelligence

* [ ] RTL normalization
* [ ] Golden dataset generation
* [ ] Dataset validation
* [ ] Dataset quality metrics
* [ ] Benchmark generation
* [ ] Reproducible dataset pipelines

### Phase 5 — RTL AI

* [ ] RTL understanding models
* [ ] RTL generation
* [ ] RTL completion
* [ ] RTL explanation
* [ ] RTL-to-knowledge tasks
* [ ] Verification generation
* [ ] Evaluation framework

---

## Relationship to Kritva

Kritva Forge is part of the broader Kritva technology ecosystem.

```text
Kritva
│
├── Kritva Core
├── Kritva Sense
├── Kritva Mind
├── Kritva Motion
├── Kritva Skill
├── Kritva Sim
├── Kritva SDK
│
├── Kritva Nexus
├── Kritva Edge
│
└── Kritva Forge
    Hardware Design Intelligence
```

Kritva Nexus and Kritva Edge are hardware platforms.

Kritva Forge is a separate hardware-design intelligence framework that can support development, analysis, verification, and understanding of hardware designs.

---

## License

Kritva Forge is intended to be released under the Apache License 2.0.

See `LICENSE` for details.

---

## Contributing

Contributions are welcome.

Please see `CONTRIBUTING.md` for development guidelines, coding conventions, tests, and contribution workflow.

---

## Project Status

**Project:** Kritva Forge
**Domain:** Hardware Design Intelligence
**Primary focus:** RTL understanding and analysis
**Repository:** `KritvaOS/kritva-forge`
**Data repository:** `KritvaOS/kritva-forge-data`
**License:** Apache License 2.0

