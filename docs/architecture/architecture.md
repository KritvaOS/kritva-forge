# Kritva Forge Architecture

## 1. Overview

Kritva Forge is a hardware design intelligence framework designed to transform RTL source code into structured design knowledge.

The architecture separates:

1. RTL parsing
2. RTL Intermediate Representation
3. Semantic analysis
4. Structural analysis
5. FSM analysis
6. Graph/dependency analysis
7. Dataset generation
8. RTL AI/LLM systems

The central architectural principle is:

> **Parse once, normalize once, analyze many ways.**

The parser produces a reusable RTL IR that becomes the common input to downstream analysis components.

---

# 2. High-Level Architecture

```text
                         RTL Source
                    Verilog / SystemVerilog
                              │
                              ▼
                    ┌──────────────────┐
                    │    RTL Parser    │
                    │                  │
                    │ PySlang / Slang  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │     RTL IR       │
                    │                  │
                    │ Modules          │
                    │ Ports            │
                    │ Signals          │
                    │ Assignments      │
                    │ Processes        │
                    │ Cases            │
                    │ Expressions      │
                    └────────┬─────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            ▼                ▼                ▼
     ┌────────────┐   ┌────────────┐   ┌────────────┐
     │ Semantic   │   │Structural  │   │  Process   │
     │ Analysis   │   │ Analysis   │   │  Analysis  │
     └──────┬─────┘   └──────┬─────┘   └──────┬─────┘
            │                │                │
            └────────────────┼────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   FSM Engine     │
                    │                  │
                    │ Candidate        │
                    │ State            │
                    │ Transition       │
                    │ Action           │
                    │ Encoding         │
                    └────────┬─────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
             ┌────────────┐    ┌────────────┐
             │   Graph    │    │  Quality   │
             │  Analysis  │    │  Analysis  │
             └─────┬──────┘    └──────┬─────┘
                   │                  │
                   └────────┬─────────┘
                            ▼
                   ┌──────────────────┐
                   │ Design Knowledge │
                   └────────┬─────────┘
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
          Dataset Generation      RTL AI / LLM
```

---

# 3. Repository Architecture

```text
kritva-forge/
│
├── docs/
│   └── architecture/
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
    └── kritva-forge-data/    # Git submodule
```

---

# 4. Parser Layer

## Responsibility

The parser converts Verilog/SystemVerilog source into a normalized representation suitable for downstream analysis.

The parser should be responsible for **syntax and source structure**, not higher-level interpretation.

### Primary responsibilities

* Module extraction
* Port extraction
* Parameter extraction
* Signal extraction
* Instance extraction
* Always/process extraction
* Assignment extraction
* Case statement extraction
* Conditional statement extraction
* Expression representation
* Source metadata
* Hierarchy information

### Parser interface

Conceptually:

```text
RTL source
    │
    ▼
Parser
    │
    ▼
Normalized RTL IR
```

The parser should not directly determine whether a signal is an FSM state register.

That belongs to structural/FSM analysis.

---

# 5. RTL Intermediate Representation

The RTL IR is the central data model of Kritva Forge.

It provides a normalized representation independent of downstream consumers.

A simplified module representation is:

```text
Module
├── name
├── parameters
├── ports
├── signals
├── instances
├── processes
├── assignments
├── case_statements
└── metadata
```

An assignment can contain information such as:

```text
Assignment
├── raw
├── lhs
├── rhs
├── operator
├── lhs_signal
├── is_blocking
├── is_nonblocking
├── is_array
└── is_hierarchical
```

A case statement contains:

```text
Case
├── expression
├── case_type
└── items
    ├── labels
    └── statements
```

The IR should remain serializable.

Raw parser AST objects should not be stored in persistent YAML/JSON representations.

---

# 6. Semantic Analysis

Semantic analysis adds meaning to the normalized structural representation.

Examples include:

* Symbol resolution
* Signal classification
* Scope resolution
* Type information
* Assignment relationships
* Expression relationships
* Process relationships
* Signal roles

The semantic layer should provide information to downstream structural and FSM analysis without coupling those components directly to the parser.

---

# 7. Structural Analysis

Structural analysis identifies relationships in the RTL.

Examples:

```text
Signal
  │
  ├── assigned by Process
  ├── read by Process
  ├── used in Case
  ├── used in Condition
  └── drives another Signal
```

Structural analysis can build:

```text
Signal dependency graph
Assignment graph
Process graph
Control-flow relationships
Data-flow relationships
```

The structural layer is particularly important for FSM detection.

---

# 8. FSM Architecture

FSM analysis is a consumer of the RTL IR and structural information.

It should not depend primarily on signal naming conventions.

The FSM pipeline is:

```text
RTL IR
  │
  ▼
Candidate Detection
  │
  ▼
Candidate Validation
  │
  ▼
State Identification
  │
  ▼
Transition Recovery
  │
  ▼
Action Recovery
  │
  ▼
Encoding Resolution
  │
  ▼
FSM Quality Analysis
  │
  ▼
FSM Graph
```

---

## 8.1 Candidate Detection

Potential state registers can be identified using structural evidence.

Useful evidence includes:

* Used as a `case` expression
* Assigned in sequential logic
* Assigned from a next-state expression
* Reset behavior
* Limited number of distinct values
* Participation in control logic
* Relationship between current-state and next-state signals

Signal names can be used as hints but should not be the fundamental detection mechanism.

---

## 8.2 Candidate Validation

A candidate should be validated before being promoted to an FSM.

A strong candidate typically has evidence such as:

```text
State register
     │
     ├── sequential assignment
     │
     ├── reset behavior
     │
     ├── case(state)
     │
     └── next-state relationship
```

This prevents high-fanout datapath signals from being incorrectly classified as FSM state registers.

---

## 8.3 State Extraction

States may be recovered from:

* Case labels
* Enumerations
* Parameters
* Localparams
* Constant assignments
* Explicit state encodings

The system should preserve both:

```text
raw label
normalized label
resolved value
```

when available.

---

## 8.4 Transition Extraction

Transitions are recovered from next-state assignments within state-specific control paths.

Conceptually:

```text
Current State
      │
      ▼
   Condition
      │
      ▼
 Next State
```

A transition should contain information such as:

```text
Transition
├── source_state
├── target_state
├── condition
└── metadata
```

Multiple current states represented by a case label must be expanded into individual transition edges where appropriate.

---

## 8.5 Action Extraction

Actions describe behavior associated with states or transitions.

Examples include:

* Output assignments
* Register updates
* Control signal changes
* Datapath operations
* Interface operations

Actions should remain separate from transition structure.

---

# 9. FSM Quality Analysis

Once an FSM graph has been constructed, additional analysis can be performed.

Potential checks include:

```text
Reachability
Unreachable states
Dead-end states
Terminal states
Self-loops
Strongly connected components
Missing transitions
Default transitions
State coverage
Transition coverage
```

This allows the framework to move beyond:

> "I found an FSM."

toward:

> "I understand the structural quality of the recovered FSM."

---

# 10. Graph and Dependency Analysis

FSMs are one type of graph within RTL.

Kritva Forge should eventually represent:

```text
Module graph
Hierarchy graph
Signal dependency graph
Assignment graph
Process graph
FSM graph
Data-flow graph
Control-flow graph
```

These graphs can become an important foundation for hardware design intelligence.

---

# 11. Dataset Architecture

Dataset generation is downstream of RTL understanding.

The pipeline is:

```text
RTL
 │
 ▼
Parser
 │
 ▼
RTL IR
 │
 ▼
Analysis
 │
 ▼
Normalized Knowledge
 │
 ▼
Dataset Builder
 │
 ├── SFT dataset
 ├── Evaluation dataset
 ├── Golden dataset
 └── Benchmark dataset
```

The dataset generation code is public.

The actual RTL corpus and generated private datasets reside in:

```text
KritvaOS/kritva-forge-data
```

---

# 12. Private Data Repository

The public repository should not contain private RTL.

The data repository is:

```text
KritvaOS/kritva-forge-data
```

and is mounted into the public project as:

```text
kritva-forge/data/
```

Conceptually:

```text
                 kritva-forge
                      │
                      │ submodule
                      ▼
              kritva-forge-data
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
      RTL          Datasets        Golden
    Corpus                         Data
```

This separation allows the public software to be released under an open-source license without exposing restricted data.

---

# 13. RTL AI / LLM Layer

The RTL AI layer consumes the structured information generated by Forge.

Potential tasks include:

```text
RTL understanding
RTL explanation
RTL summarization
RTL generation
RTL completion
RTL transformation
FSM reasoning
Verification generation
Assertion generation
Bug detection
Design knowledge extraction
```

The LLM should not be tightly coupled to the parser.

Instead:

```text
RTL → IR → Knowledge → Dataset → Model
```

This makes it possible to change the model without redesigning the RTL analysis infrastructure.

---

# 14. Pipeline Orchestration

The main pipeline should orchestrate the individual subsystems.

```text
run_pipeline.py
      │
      ├── Parser
      │
      ├── RTL IR
      │
      ├── Semantic
      │
      ├── Structural
      │
      ├── FSM
      │
      ├── Graph
      │
      ├── Quality
      │
      └── Dataset
```

Each subsystem should remain independently testable.

---

# 15. Testing Architecture

Testing should be organized by architectural layer.

```text
tests/
├── parser/
├── rtl_ir/
├── semantic/
├── structural/
└── fsm/
```

Tests should cover both:

### Unit tests

Individual functions and components.

### Integration tests

Complete RTL → IR → analysis flows.

### Regression tests

Known RTL examples whose expected results are maintained.

### Golden tests

Expected normalized IR/FSM representations for selected RTL designs.

---

# 16. Versioning

The RTL IR should have an explicit schema version.

For example:

```yaml
schema_version: "1.0"
parser_version: "0.1"
```

This is important because datasets generated from one version of the IR should remain identifiable when the parser evolves.

---

# 17. Architectural Boundaries

The following boundaries should be maintained:

```text
Parser
  ↓
RTL IR
  ↓
Semantic
  ↓
Structural
  ↓
FSM / Graph / Analysis
  ↓
Dataset
  ↓
AI / LLM
```

Avoid:

```text
FSM → directly parse RTL
Dataset → directly inspect AST
LLM → directly depend on parser internals
Reports → modify analysis state
```

This separation keeps the architecture maintainable.

---

# 18. Future Expansion

The architecture is intentionally designed to support future hardware intelligence capabilities.

Potential future components include:

```text
Timing Intelligence
        │
PPA Intelligence
        │
Verification Intelligence
        │
DFT Intelligence
        │
Formal Intelligence
        │
Architecture Understanding
        │
RTL Generation
        │
       ...
        │
        ▼
Kritva Forge
```

The goal is for Kritva Forge to evolve from an RTL analysis framework into a broader **hardware design intelligence platform**.

---

# 19. Relationship with Kritva Nexus and Kritva Edge

Kritva Forge is architecturally independent from the Kritva hardware platforms.

```text
                 Kritva
                    │
       ┌────────────┼─────────────┐
       │            │             │
       ▼            ▼             ▼
   Nexus           Edge         Forge
   SoC             SoC        Design AI
       │            │             │
       │            │             │
       └────────────┼─────────────┘
                    │
             Hardware Ecosystem
```

Kritva Forge may eventually consume and analyze RTL from Kritva Nexus and Kritva Edge.

However:

> **Kritva Forge is not the RTL repository for Kritva Nexus or Kritva Edge.**

This distinction should remain explicit.

---

# 20. Long-Term Vision

Kritva Forge aims to build a machine-readable representation of hardware design intent.

The long-term flow is:

```text
                    Human Design
                         │
                         ▼
                        RTL
                         │
                         ▼
                  ┌──────────────┐
                  │Kritva Forge  │
                  └──────┬───────┘
                         │
              Hardware Design Knowledge
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
      Analysis       Verification      AI
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                Better Hardware Design
```

The fundamental objective is:

> **Turn RTL from source code into structured, queryable, machine-understandable hardware design knowledge.**

