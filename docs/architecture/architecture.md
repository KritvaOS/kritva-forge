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

## 5.1 Provenance and Stable Node Identity

Every persisted IR node carries portable provenance (KF-DQ-002) and a
deterministic content identity (KF-DQ-003):

```yaml
identity_version: 1                       # module-level identity model version
...
- node_id: n1:4fc1e05d2cb15eab            # stable content identity
  syntax_type: ParameterDeclarationStatementSyntax
  source_file: raw/rtl/original/uart/uart_tx.v   # top-level RTL file (repo-relative)
  offset: 342
  buffer: raw/rtl/original/uart/uart_tx.v        # file that physically holds the token
```

`node_id` is `n<version>:` plus the first 16 hex digits of SHA-256 over:

```text
"kf-node" | "v1" | source_file | syntax_kind | start location key | end location key
```

A location key is `file|offset`; for macro-expanded tokens it is
`expanded_file|expanded_offset|macro|spelling_file|spelling_offset|macro_offset`.
All files are repository-relative.

The identity never uses `id()`, Python `hash()`, UUIDs, timestamps, process,
host or user information, absolute paths, or pyslang `BufferID` allocation
numbers. It is therefore identical across repeated runs, relocated data roots
and parse order. Two nodes share an identity only if they are the same syntax
kind with exactly the same start and end token positions in the same source
file. The implementation and full specification live in
`scripts/core/identity.py`; any change to the payload must bump
`IDENTITY_VERSION`.

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

## 11.1 Leakage-Safe Splits

Train / validation / test assignment is deterministic and leakage-aware
(`scripts/dataset/leakage.py`, `LEAKAGE_SCHEMA_VERSION = 1`).  There is no
random seed; the split depends only on record content.

Every record carries versioned identities:

| Kind | Identities | Rule |
|------|------------|------|
| Hard | `source_rtl`, `module_body`, `normalized_ir`, `completion` | must never cross splits |
| Soft | `body_shape` (identifier-agnostic), `module_name` | reported only |
| Info | `ip` | reported only |

Records sharing any hard identity are joined into one leakage group.
`body_shape` also joins groups when the same shape appears in more than one
IP (cross-IP near-duplicates).  Groups spanning several IPs are shared
library code and are assigned to `train`; each IP's remaining records form
one atomic unit, placed largest first into the split furthest below its
target (70 / 15 / 15).

The assignment is written to `splits/split_manifest.json` and the gate
report to `analysis/reports/split_leakage_report.json`.  Dataset generation
fails if any hard group crosses splits, a record is duplicated, or the
manifest disagrees with the dataset files.  `make check-leakage` re-runs the
gate against an existing data checkout.


## 11.2 RTL Provenance

Every canonical module is traceable from dataset record back to source RTL
(`scripts/core/provenance.py`, `PROVENANCE_VERSION = 1`):

```text
raw/rtl/original/<ip>/...              source file      sha256(file bytes)
  -> normalized/ir/<ip>/modules/<m>    normalized IR    sha256(YAML bytes)
  -> generated/prompts/<ip>/<m>.*      prompts          sha256(prompt bytes)
  -> datasets/pipeline/<split>.jsonl   dataset records  record_id (KF-DQ-004)
```

The canonical manifest is `manifests/provenance_manifest.json` in the data
repository, and the validation report is `analysis/reports/provenance_report.json`.

Each module entry records:

- `module_id`
- `source` (path and sha256)
- `contributing_sources` (the primary file plus include files, each with role and sha256)
- `unresolved_includes` and `external_includes`
- `normalized_ir`:
  - path
  - sha256
  - `ir_content`, the location-free KF-DQ-004 identity
- `module_body`
- `prompts`
- `artifacts` (the `normalized/ir/<ip>/rtl/` copy of the source)
- `dataset_records` (record_id and split for each record)
- `transformation` status

The manifest also has a `sources` index that lists every source file with its
sha256 and the modules it feeds. The pipeline and schema versions are recorded
at the top level.

Identities are kept distinct:

| Identity | Form | Meaning |
|---|---|---|
| source | 64-hex sha256 | Exact content of one RTL file |
| module | `mod1:` + 16 hex of sha256(`kf-module`, `v1`, ip, module) | Logical canonical module `<ip>/<module>` |
| module body | `m1:...` (KF-DQ-004) | Module text with comments and whitespace removed |
| normalized IR | sha256 of the YAML file; `ir_content` `n1:...` (KF-DQ-004) | Exact IR file; IR content without location fields |
| IR node | `n1:...` `node_id` (KF-DQ-003) | One IR node |
| dataset record | `r1:...` (KF-DQ-004) | One (ip, module, task, prompt_variant) record |

**Dataset records** carry a compact `provenance` block:

- `record_id`
- `module_id`
- source path and sha256
- IR path and sha256
- `generated_artifact`

The RTL text is not duplicated in this block. `generated_artifact` is `null` unless a curated RTL file replaced the completion.

`rtl_source` is `original`, or `curated` when a curated RTL file was used. It was previously mislabelled `generated`.

**Policies:**

- **Paths** are POSIX and relative to the data root (KF-DQ-002).
- **Hashes** are SHA-256 of raw bytes, with no mtime, PID, UUID, object id or absolute path.
- **Ordering:** all lists are sorted, and JSON is written with sorted keys.

The manifest is byte-identical across runs and checkout locations. Any change to the identity or manifest format bumps `PROVENANCE_VERSION`.

Canonical normalized IR is not changed by KF-DQ-005.

**Missing or external sources:**

- A missing primary source fails validation.
- An unconditional `` `include`` that cannot be resolved fails validation.
- A conditional include inside `` `ifdef``/`` `ifndef`` that is not part of the corpus is recorded under `external_includes` and reported, not failed. Macros are not evaluated. An example is yifive's optional `ycr_arch_custom.svh`.

Includes are resolved in this order:

1. The including file's directory.
2. The IP's `files.f` `+incdir+` directories.
3. A unique basename match inside the IP.

**Regeneration and validation:** `make pipeline` rewrites the manifest and fails if validation fails. `make check-provenance` (`python3 scripts/core/provenance.py --check`) recomputes the manifest from the data tree and fails on any of these:

- missing, orphan or duplicate records
- missing or duplicate module identities
- invalid or incorrect hashes
- absolute paths
- unresolved sources or includes
- invalid IR references
- a schema-version mismatch
- dataset records without traceability
- a stored manifest that differs from the recomputed one

`--write` regenerates the manifest in place.


## 11.3 Stale Generated Artifacts

`scripts/core/stale_artifacts.py` (`ARTIFACT_SCHEMA_VERSION = 1`) decides,
deterministically, whether each generated artifact is valid for the current
canonical data.

**Canonical** artifacts are the inputs and the canonical IR:

- `raw/rtl/original/`
- `normalized/ir/<ip>/{modules/*.yaml, hierarchy.yaml, summary.yaml, rtl/*}`

**Generated** artifacts are derived from them:

- `generated/prompts/`
- `analysis/reports/`
- `datasets/pipeline/`
- `splits/`
- `manifests/`
- `golden/`

Every file under the managed roots is in exactly one state:

| State | Meaning |
|---|---|
| `CURRENT` | In the expected inventory and verified against current inputs |
| `STALE` | Content, schema or identity no longer current, or a superseded duplicate of a canonical artifact (e.g. old `analysis/reports/<ip>/*.yaml`, `generated/rtl/pipeline/*` copies of raw RTL) |
| `ORPHAN` | Refers to a module, IP or record that no longer exists |
| `HISTORICAL` | Retained and never consumed: `*/legacy/`, `datasets/source/`, the KF-DQ-001 migration manifests, and quarantined files |
| `UNMANAGED` | Not part of the output contract, including symlinks and unknown top-level directories |

**Expected inventory.** The expected inventory is computed from three inputs:

- raw RTL
- the canonical IR
- the KF-DQ-005 provenance model, recomputed rather than read back

Existing outputs never define what should exist.

**Freshness** is based on identities and recomputation. Filesystem modification time is not used and is not sufficient. The checks are:

- **Prompts:** must equal `generate_module_prompt(<IR>)`.
- **Canonical IR:** stale when its source sha256 differs from the one recorded in the stored provenance manifest; orphan when its source is missing or no longer declares the module.
- **Dataset records:** must carry the current provenance version, `record_id`, `module_id`, source sha256 and IR sha256.
- **Split-manifest entries:** must reference current records.
- **Manifests and reports:** must carry the current schema version and match a recomputation.

**Outputs:**

- `manifests/artifact_inventory.json`: path, kind, state, ip, module, `module_id`, source sha256 and sha256 for each file.
- `analysis/reports/stale_artifact_report.json`: counters and the remediation plan.

Both are byte-identical across runs and checkout locations.

**Remediation:**

| Action | Applies to |
|---|---|
| `REGENERATE` | Rerun the pipeline: stale expected outputs and canonical IR |
| `REMOVE` | Orphans and superseded duplicates |
| `QUARANTINE` | Unmanaged files; moved to `generated/legacy/quarantine/<path>`, which makes them historical |
| `MANUAL` | Symlinks |

**Commands:**

| Command | Effect |
|---|---|
| `make check-stale` | Read-only gate (`stale_artifacts.py --check`) |
| `make clean-stale` | Dry-run plan |
| `make clean-stale APPLY=1` | Executes `REMOVE` and `QUARANTINE` and prints every action |

**Cleanup safety.** Cleanup only touches files under `generated/`, `analysis/reports/`, `datasets/pipeline/`, `splits/`, `manifests/` or `golden/`, outside the historical paths. It never touches `raw/` or `normalized/`. It rejects:

- absolute paths, `..` and symlinks
- anything that resolves outside the data root

All actions are validated before any is executed, and one unsafe entry aborts the cleanup.

**Pipeline gate:**

1. After IR and prompts are regenerated, a pre-dataset gate runs. If any stale, orphan or unmanaged artifact exists, it aborts before datasets, splits or provenance are written.
2. After all outputs are written, the inventory and report are written and the full gate runs again.

`KRITVA_FORGE_ALLOW_STALE=1` is an explicit override. It is recorded as `override: true` in the report, and the report status stays `FAIL`.

**Split, provenance and relocation.** The KF-DQ-004 split, the leakage gate and KF-DQ-005 provenance are consumed unchanged. A stale record or split entry fails the gate before it can reach a dataset. Paths are repository-relative, so moving the data repository changes no classification.

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

Node identity is versioned separately as `identity_version`
(see section 5.1).

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

