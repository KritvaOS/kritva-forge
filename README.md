# Kritva Forge

## Hardware Design Intelligence

Kritva Forge is an open-source hardware design intelligence framework for understanding, analyzing, and learning from RTL designs.

The project provides a structured pipeline for transforming Verilog/SystemVerilog RTL into machine-readable design knowledge, enabling structural analysis, FSM extraction, dependency analysis, dataset generation, and RTL-oriented AI/LLM research.

Kritva Forge is **not** the RTL implementation of Kritva Nexus or Kritva Edge. It is a separate engineering and research framework that can eventually be used to analyze and understand those designs.

## Vision

Modern hardware designs contain significant architectural knowledge distributed across RTL source code, hierarchy, signals, processes, state machines, dependencies, and design intent. Kritva Forge aims to make this knowledge accessible to both engineers and AI systems.

```text
RTL → RTL Parsing → Normalized RTL IR → Semantic / Structural / FSM Analysis → Design Knowledge → Dataset / RTL AI
```

## Current Scope

- Verilog/SystemVerilog RTL parsing
- Normalized RTL Intermediate Representation (IR)
- Module and hierarchy analysis
- Port and signal analysis
- Assignment and process analysis
- Semantic and symbol analysis
- Structural RTL analysis
- FSM candidate detection and extraction
- State and transition analysis
- FSM quality analysis
- Dependency and graph analysis
- RTL dataset generation
- Golden dataset generation
- RTL AI/LLM experimentation
- Evaluation and regression analysis

## Repository Structure

```text
kritva-forge/
├── docs/
├── scripts/
│   ├── parser/
│   ├── rtl_ir/
│   ├── semantic/
│   ├── structural/
│   ├── fsm/
│   ├── analysis/
│   ├── dataset/
│   ├── debug/
│   ├── pipeline/
│   └── core/
├── tests/
├── examples/
├── schemas/
├── configs/
└── data/
```

`data/` contains only public-repository documentation. Runtime RTL and
generated artifacts are stored in the separate private
`KritvaOS/kritva-forge-data` repository.

## Design Principles

### Parse once, analyze many ways
The parser produces a reusable normalized RTL IR that downstream components consume.

### Separate parsing from understanding
Parsing describes source structure. Semantic, structural, FSM, and graph analysis add higher-level meaning.

### Serializable persistent IR
Persistent YAML/JSON representations must not contain raw parser AST objects.

### Structural FSM detection
FSM detection should use structural and semantic evidence rather than relying on signal naming conventions alone.

### Public code / private data
Algorithms, tools, tests, schemas, and documentation are public. Private RTL corpora and restricted datasets remain in `kritva-forge-data`.

## Development Status

Kritva Forge is under active development. The initial implementation focuses on RTL parsing, normalized RTL IR, semantic and structural analysis, FSM extraction, transition recovery, quality analysis, dataset generation, and RTL AI/LLM experimentation.

## Relationship to Kritva

```text
Kritva
├── Kritva Core
├── Kritva Sense
├── Kritva Mind
├── Kritva Motion
├── Kritva Skill
├── Kritva Sim
├── Kritva SDK
├── Kritva Nexus
├── Kritva Edge
└── Kritva Forge
    Hardware Design Intelligence
```

Kritva Nexus and Kritva Edge are hardware platforms. Kritva Forge is a separate hardware-design intelligence framework that may analyze their RTL in the future.

## License

Apache License 2.0.


## Public Code / Private Data

Kritva Forge intentionally separates algorithms from RTL/data:

```text
kritva-forge/
    parser / IR / semantic / structural / FSM / dataset code
                 │
                 ▼
kritva-forge-data/
    raw/rtl → normalized/ir → analysis/golden → datasets/generated
```

For the standard local layout:

```bash
cd ~/workarea/kritvaos/kritva-forge
make setup
make headers
make test
make pipeline
```

The pipeline reads `../kritva-forge-data/raw/rtl` and writes to the dedicated
private-data directories. All paths can be overridden through Make variables.

## Pipeline Outputs

| Artifact | Default location |
|---|---|
| Raw RTL input | `kritva-forge-data/raw/rtl` |
| Normalized module IR | `kritva-forge-data/normalized/ir` |
| Generated prompts | `kritva-forge-data/generated/prompts` |
| Pipeline reports | `kritva-forge-data/analysis/reports` |
| Pipeline datasets | `kritva-forge-data/datasets/pipeline` |
