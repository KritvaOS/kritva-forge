# Kritva Forge Architecture

## 1. Overview

Kritva Forge transforms RTL source code into structured hardware design knowledge.

The architecture separates RTL parsing, RTL Intermediate Representation, semantic analysis, structural analysis, FSM analysis, graph/dependency analysis, dataset generation, and RTL AI/LLM systems.

> **Parse once, normalize once, analyze many ways.**

## 2. High-Level Flow

```text
RTL Source
   ↓
RTL Parser
   ↓
Normalized RTL IR
   ├── Semantic Analysis
   ├── Structural Analysis
   ├── Process Analysis
   ↓
FSM / Graph / Quality Analysis
   ↓
Design Knowledge
   ├── Dataset Generation
   └── RTL AI / LLM
```

## 3. Layers

### Parser
Converts Verilog/SystemVerilog into normalized source structure: modules, ports, parameters, signals, instances, processes, assignments, cases, expressions, and metadata.

The parser should not decide whether a signal is an FSM state register.

### RTL Intermediate Representation
The IR is the common representation for downstream consumers. It represents modules, ports, signals, assignments, processes, cases, expressions, and metadata in serializable form.

### Semantic Analysis
Adds symbol resolution, scopes, types, signal classification, expression relationships, and semantic quality information.

### Structural Analysis
Builds assignment, signal-dependency, process, data-flow, and control-flow relationships.

### FSM Engine
The FSM pipeline is:

```text
Candidate Detection
       ↓
Candidate Validation
       ↓
State Identification
       ↓
Transition Recovery
       ↓
Action Recovery
       ↓
Encoding Resolution
       ↓
FSM Quality Analysis
       ↓
FSM Graph
```

Candidate validation should use structural evidence such as case usage, sequential assignment, reset behavior, and next-state relationships. Naming conventions are only hints.

### Graph and Quality Analysis
Potential analyses include reachability, unreachable states, dead ends, terminal states, self loops, strongly connected components, missing/default transitions, and transition coverage.

### Dataset and AI
Normalized design knowledge feeds dataset generation and eventually RTL understanding, explanation, generation, verification, assertion generation, bug detection, and related AI tasks.

## 4. Repository Boundaries

```text
scripts/parser      RTL parsing
scripts/rtl_ir      Normalized RTL representation
scripts/semantic    Semantic analysis
scripts/structural  Structural analysis
scripts/fsm         FSM analysis
scripts/analysis    Reports and analysis utilities
scripts/dataset     Dataset generation
scripts/pipeline    End-to-end orchestration
scripts/debug       Diagnostics
scripts/core        Shared infrastructure
tests               Regression and unit tests
```

## 5. Public / Private Data Boundary

The public repository contains source code, algorithms, tests, schemas, examples, and documentation.

The private repository `KritvaOS/kritva-forge-data` contains RTL corpora, generated datasets, golden data, benchmarks, and restricted/proprietary material. It is mounted as the `data/` Git submodule.

## 6. Versioning

The persistent RTL IR should carry explicit schema and parser versions, for example:

```yaml
schema_version: "1.0"
parser_version: "0.1"
```

This keeps generated datasets traceable as the parser and IR evolve.

## 7. Testing

Testing is organized by architectural layer:

```text
tests/parser
tests/rtl_ir
tests/semantic
tests/structural
tests/fsm
```

The project should maintain unit, integration, regression, and golden-data tests.

## 8. Relationship to Kritva Nexus and Kritva Edge

Kritva Forge is independent of the Nexus and Edge SoC repositories. It may consume and analyze their RTL, but it is not their RTL implementation repository.

```text
Kritva Nexus ─┐
              ├── Hardware ecosystem
Kritva Edge  ─┘
       
Kritva Forge ─── Hardware Design Intelligence
```

## 9. Long-Term Direction

The long-term goal is to turn RTL from source code into structured, queryable, machine-understandable hardware design knowledge, supporting analysis, verification, and AI-assisted hardware design.
