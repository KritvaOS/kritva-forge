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

## 5.2 Semantic IR v2 (KF-DQ-008)

**Purpose.** The v1 module YAML (`normalized/ir/<ip>/modules/<module>.yaml`)
describes structure: ports, signals, parameters and instances. Its
behavioural fields (`always_blocks`, `assigns`, `num_*`) are always empty
because of a key mismatch: the parser stores `continuous_assigns` /
`processes`, while `yaml_generator` reads `assigns` / `always_blocks`.
Semantic IR v2 is a separate, versioned, source-level semantic
representation. It covers declarations, types, expressions, assignments,
conditions, cases, instances and symbol references. Downstream tasks
consume it through this documented contract instead of parser-specific
fields.

**Output location and versions.** There is exactly one canonical location:
`normalized/semantic_ir/v2/<ip>/<module>.json`, one document per canonical
module. The v1 IR is not touched. Both representations are independently
valid and independently tested. Consumers name the version they read
(`normalized/ir` v1 or `normalized/semantic_ir/v2`).

Every document carries:

- `schema: {name: kritva-forge-semantic-ir, version: 2}`
- `versions`:
  - `schema`: 2
  - `identity`: 1, the `sem1:` namespace
  - `node_identity`: the KF-DQ-003 `n1` version
  - `parser`, for example `pyslang 12.0.0`
  - `compatibility.normalized_ir`: 1

Serialisation is canonical and byte-deterministic: sorted keys, compact
separators, UTF-8 and a trailing newline. The corpus is about 32 MB; use
`python -m json.tool` to read a document. The contract is in
`scripts/semantic_ir/model.py`. The generator is `extractor.py`, called from
`rtl_parser_slang` and `yaml_generator.write_semantic_ir`. The validator is
`validator.py`.

**Schema** (document sections):

| Section | Content (criteria §6) |
|---|---|
| `module` | name, `id` (`sem1:`), `module_id` (`mod1:`, KF-DQ-005), `ip`, `is_top`, `source {path, sha256}`, `loc` |
| `parameters` | parameter / localparam / genvar: type, signedness, packed dimensions, `width` (null when untyped), default expression, constant `value`, `port_param`, `loc` |
| `ports` | in declaration order: direction (input/output/inout/ref/unknown), net/variable `kind`, type, `signed`, `packed` / `unpacked` dimensions, `width`, `default`, ANSI or non-ANSI style, `loc` |
| `signals` | nets and variables (implicit nets marked): `kind` and `net_type` distinguish wire/net from logic/reg/integer variables; same type fields as ports |
| `typedefs` | enum (members with values; anonymous enums have `name: null`), struct/union, alias |
| `subroutines` | functions and tasks: ports (the return value is a `return`-direction port), body |
| `assignments` | target and value expressions, `kind` (continuous / blocking / nonblocking / compound / declaration), operator, referenced symbols (`writes`, `reads`), `guards`, owner (`process` / `subroutine` / `generate`), scope, `loc` |
| `processes` | containers for procedural code: `kind` (keyword), `sensitivity` as written (`list` / `implicit` / `none`), `events` (edge + expression), statement `body`, assignment ids |
| `conditions` | one record per `if`: owner, unique/priority qualifier, `predicate_references`, `then` / `else` statement ids, `loc` |
| `cases` | one record per case: `case_kind` (case/casez/casex), qualifier, `selector_references`, `items` (label count, `label_references`, body), `default`, `loc` |
| `instances` | instance name, referenced `module`, `resolved` and `target_module_id` (null when unresolved), parameter overrides, connections (named/ordered/implicit/wildcard/empty, port, expression, direction), `loc` |
| `generates` | region / loop / if / case / block, `representation: source-level` (not elaborated) |
| `references` | one record per symbol **use** (see below) |
| `external` | compilation-unit declarations from `include`d headers |
| `unsupported` | every construct that is not modelled |
| `coverage`, `counts`, `extraction`, `generator` | accounting, and `complete` or `partial` |

**Expressions** are trees that preserve operand order:

- `ref`: `id`, name, `ref_kind`, and `target` (the defining entity, or null)
- `literal`: text, value, base, width, `has_xz`
- `unary`, `binary`, `ternary`
- `concat`, `replicate`
- `index`, `part_select` (`:`, `+:`, `-:`)
- `member`
- `call`: system or user function, with arguments
- `cast`
- `opaque`

Constant parameter expressions, including `$clog2`, and widths are evaluated
where determinable; otherwise they are null.

Statement trees inside processes and subroutines are made of:

- `assign`
- `if`
- `case`
- `block`
- `loop`
- `timing`
- `null`
- `return`
- `call`
- `declaration`
- `opaque`

**Declarations and references.** Declarations are the entities in
`parameters`, `ports`, `signals`, `typedefs` (and their enum members),
`subroutines`, genvars and block-local declarations. Each use of a symbol
is a `ref` expression node with its own identity. `references` indexes
every use with these fields:

| Field | Meaning |
|---|---|
| `symbol` | the name used |
| `ref_kind` | port, signal, parameter, genvar, local, enum_member, subroutine, type, external, hierarchical or unresolved |
| `target` | the defining entity |
| `source` | the referencing entity: an assignment, statement, process, instance, declaration or generate |
| `usage` | `read`, `write` (the written base of an assignment target) or `connect` (an instance port expression) |
| `loc` | the source span |

Names that cannot be resolved stay explicit as `unresolved` with a null
target. Nothing is guessed.

**Assignments and guards.** `guards` lists the enclosing control constructs,
outermost first. Each entry is `{statement, branch}`, where `branch` is
`then`, `else`, `item` (with the `item` index), `default` or `body`. It
records where an assignment sits without claiming execution semantics.

**Identity.** Every semantic entity has
`id = "sem1:" + sha256("kf-sem", "v1", category, n1, qualifier)[:16]`,
where:

- `n1` is the KF-DQ-003 node identity (repository-relative file, syntax kind, token positions);
- `category` is the entity kind;
- `qualifier` disambiguates several entities derived from one syntax node.

When one type is shared by several declarators, copies of its range
expressions get reference identities derived from (reference identity,
declarator). Identities are stable across runs, parse order and checkout
location, and change only when the RTL changes. Modules keep `mod1:`;
source identity is the content sha256.

**Provenance.** The module records `source {path, sha256}`. Every entity,
statement, reference and unsupported record carries `loc {file, line,
column, offset}`. The path is repository-relative and names the physical
buffer, so an `include`d header gives the header's path. For
macro-expanded tokens, `loc` is the fully original location. No
machine-local path is persisted.

**Unsupported constructs.** Unsupported constructs are explicit, never
dropped. Each one becomes an `opaque` statement, expression or member node
and is listed in `unsupported` with construct, level, reason, text and
`loc`. When anything is opaque, `extraction` is `partial`. Examples are
`wait`, `case … inside` and `force`.

**Validation (fail closed).** `scripts/semantic_ir/validator.py` (also
`make check-semantic`) runs two levels of checks.

Per-document checks:

- schema and identity versions
- required fields and enumerations
- missing, malformed or duplicate identities
- duplicate declarations
- provenance presence and portability (absolute paths, `..`)
- port directions
- widths (positive, and consistent with constant packed ranges)
- expression, statement, assignment, condition and case structure
- references: unresolvable targets, resolvable kinds without a definition, and index ↔ tree agreement
- instance resolution
- canonical ordering
- silent loss of unsupported constructs

Corpus checks:

- one document per canonical module
- duplicate module identities
- duplicate canonical output paths
- canonical bytes
- current source sha256

The corpus report is written to `analysis/reports/semantic_ir_report.json`
and includes `corpus_sha256`.

**Gates and data manifest.** The pipeline parses the RTL and writes the v1 IR
and Semantic IR v2. The gates then run in this order:

1. pre-dataset stale gate
2. Semantic IR v2 gate (no override)
3. datasets
4. provenance
5. post-run stale gate
6. data manifest gate

The stale gate classifies `normalized/semantic_ir/v2` documents. A document
is CURRENT only when its schema, `mod1:`, source path/sha256 and validation
are all current. A document for a non-canonical module is ORPHAN; any other
file there is UNMANAGED. The report's `corpus_sha256` is checked after the
run.

The data manifest (version 2) gives each module
`semantic_ir {path, sha256, schema_version, identity_version, status,
derived_from {source, source_sha256}}`, plus `versions.semantic_ir`,
`semantic_identity` and `semantic_parser_version`. Invalid Semantic IR is
never published. A version-1 manifest is rejected and regenerated.

**Compatibility and boundaries.**

- v1 IR, prompts, datasets, splits, provenance and all identities are
  unchanged. Semantic IR v2 is additive; nothing is overwritten.
- The v1 behavioural fields remain empty. They are superseded by
  `assignments`, `processes`, `conditions` and `cases`.
- Not in KF-DQ-008:
  - process roles, scheduling and complete behavioural semantics (KF-DQ-009)
  - driver, dependency and connectivity graphs (KF-DQ-010)
  - FSM extraction (KF-DQ-011)
  - elaboration of generates
  - timing / PPA and assertions

  KF-DQ-008 records the representation they build on: containers, guards,
  references and instances.

## 5.3 Behavioral Semantics v1 (KF-DQ-009)

**Purpose.** Semantic IR v2 (§5.2) records *what is written*: processes,
events, assignments, conditions, cases and references. Behavioral Semantics
v1 interprets those structures as hardware behaviour: process roles, clocks,
resets, registers, enables, holds, priority, combinational completeness,
latches and state candidates. It supplies the documented behavioural
contract that structural analysis (KF-DQ-010), FSM integration (KF-DQ-011)
and behaviour-aware datasets (KF-DQ-012/013) consume.

**Dependency and location.** The flow is RTL → Semantic IR v2 → Behavioral
Semantics v1.

- `scripts/behavior/analyzer.py` reads only the persisted Semantic IR v2 JSON.
  It does not parse RTL, does not use parser objects, and does not copy
  Semantic IR expression trees; records refer to `sem1:` identities instead.
- Semantic IR documents are never modified.
- Output is one document per canonical module at
  `normalized/behavior/v1/<ip>/<module>.json`, with
  `schema: {name: kritva-forge-behavioral-semantics, version: 1}`.
- Each document's `versions` block gives the behavioral schema (1), the
  behavioral identity (1, `beh1:`), the consumed Semantic IR schema (2) and
  the Semantic IR identity (1).
- `module` carries the `mod1:` module identity, the Semantic IR module
  identity, the RTL source path and sha256, and the path and sha256 of the
  analysed Semantic IR document.
- Serialisation is canonical: sorted keys, compact separators, trailing
  newline.

**Sections.**

| Section | Content |
|---|---|
| `processes` | one record per Semantic IR process: `role`, `confidence`, evidence, read/write summary (`reads`, `writes`, `conditional_reads`, `conditional_writes`, `registered_targets`, `combinational_targets`, `latch_targets`), clocks, resets, registers, enables, holds, and the process's conditions, cases and assignments |
| `clocks` | signal, edge, event index, status (confirmed / candidate / ambiguous), evidence, location |
| `resets` | signal, kind (async / sync), polarity (active_high / active_low), status, the `if` condition and branch, priority rank, per-target reset assignments, evidence |
| `registers` | register candidates of sequential processes: clock, resets, assignment kinds, ordered assignments with guards and `overridden_by`, `update`, `hold`, priority leaves, enables, holds, next values |
| `next_values` | each non-reset, non-hold update: assignment, guards, value kind (constant / expression), value references |
| `enables` | a condition whose one branch updates the register while the other branch only holds it: update/hold branch, explicit or implicit hold |
| `holds` | explicit holds (`q <= q`, including a default hold before a conditional update) and implicit holds (the missing branch) with their guard path |
| `combinational` | each target of a combinational or latch process: completeness (complete / conditional / incomplete / ambiguous), missing branches, latch status, ordered assignments |
| `latches` | targets whose latch status is explicit (`always_latch`), inferred (incomplete), possible (case without default) or ambiguous |
| `candidates` | `state_candidate` and `next_value_candidate` records. No FSM is built. |

**Process roles** are `sequential`, `combinational`, `latch`,
`initialization`, `generic`, `unknown` or `ambiguous`. They are derived from
the keyword, the event structure, the assignment kinds and the assignment
completeness:

| Process | Role | Confidence |
|---|---|---|
| `always_ff` with edge events | sequential | high when all assignments are nonblocking, otherwise medium |
| plain `always` with edge events | sequential | medium when all assignments are nonblocking, otherwise low |
| `always_comb` | combinational | high; medium when a target is not completely assigned |
| `always_latch` | latch | high |
| `@*`, or a level list that covers every signal read | combinational | medium; low when a target is only conditionally or ambiguously assigned |
| `@*` or complete level list with an incomplete target | latch (inferred) | medium |
| level list that misses a read signal | generic | low |
| no event control (procedural timing) | generic | low or unknown |
| mixed edge and level events, or keyword/event conflicts | ambiguous | unknown |
| `initial` / `final` | initialization | high |

Opaque (unsupported) statements lower confidence by one level. Confidence
reflects how complete the evidence is. Every non-unknown classification
carries `evidence`: `{code, refs}` items whose codes come from a fixed
vocabulary and whose refs are Semantic IR identities.

**Clocks and resets.** These come from event and control structure, never
from names.

- **Asynchronous reset:** an event signal tested by the leading `if` /
  `else if` chain, whose branch assigns only constants. It is **confirmed**
  when the edge agrees with the polarity (negedge ↔ `!rst`, posedge ↔
  `rst`), and **ambiguous** otherwise.
- **Clock:** the remaining edge-event signal. It is **confirmed** when it is
  not read in the process body.
- **Synchronous reset:** in a single-clock process, a leading `if` on a 1-bit
  non-clock signal with a constant-only branch and an `else` branch. It is
  always a **candidate**, because structure alone cannot tell it apart from
  a constant load.
- **Polarity** comes from the test form: `s`, `!s`, `~s`, `s == 0/1`,
  `s != 0/1`.

**Registers, priority, enables and holds.** Each register gets priority
*leaves* in if-else order:

- `reset` (under the reset branch),
- `update`,
- `hold_explicit`,
- `hold_implicit` (a branch that leaves the register unassigned).

Ranks preserve nested-condition priority, so `if (rst) … else if (en) …
else q <= q` gives reset > enable > hold. Reset leaves always rank first.

`update` is classified as unconditional, conditional, case, mixed or
reset_only. `hold` is none, explicit, implicit, mixed or ambiguous; it is
ambiguous when an opaque statement or loop prevents a decision.

**Combinational completeness** is computed over the control-path lattice
`none < partial < unknown < conditional < full`:

- an `if` without `else` makes a target incomplete;
- a `case` without `default` whose items all assign makes it conditional,
  because the selector coverage is unknown;
- slice writes and loops make it ambiguous;
- an earlier whole assignment covers later missing branches.

**State candidates** are conservative and never decided by name. All of the
following must hold:

- the register has a finite width of 2–64 bits;
- it has no arithmetic self-feedback (counters are excluded);
- **one of:**
  - **one-process:** the register selects (case selector or `if` predicate)
    updates of itself to at least two distinct constants;
  - **two-process:** the register's next value is a single combinational
    signal whose assignments are selected by the register and take at least
    two distinct constants. That signal becomes a `next_value_candidate`.

KF-DQ-009 does not build a transition graph, classify encodings or score
FSMs; that is KF-DQ-011.

**Naming guardrail.** Names such as `*_clk`, `*_rst`, `*_next` and `state`
only add a descriptive `name_hint` evidence item. The validator rejects any
classification whose only evidence is `name_hint`.

**Identity and provenance.** Every behavioral object has
`id = "beh1:" + sha256("kf-beh", "v1", category, anchor, qualifier)[:16]`,
where the anchor is a Semantic IR v2 identity (process, signal, statement or
assignment). Identities are therefore stable across runs and relocation.
Every record carries `loc` (repository-relative file:line:col) and, where
applicable, `semantic` (the `sem1:` identities it was derived from).

**Validation and gates.** `scripts/behavior/validator.py` (also
`make check-behavior`, run by `data-quality`) fails closed. Per document it
checks:

- schema and versions
- required fields and enumerations
- `beh1:` identities and duplicates
- provenance and portability
- canonical ordering
- evidence presence and the naming-only rule
- role/evidence consistency, for example: a sequential role needs edge
  evidence; high confidence needs `always_ff` and nonblocking assignments;
  a combinational process may have no edges
- clock/event agreement (index, edge, signal)
- reset agreement (signal, polarity and event-list membership against the
  `if` test)
- register / combinational / latch consistency with the process role
- the enable ↔ hold relationship and explicit holds being real
  self-assignments
- reset-first priority
- consistency with the Semantic IR document: module, source, sha256, the
  process set and every assignment and statement reference
- counts

Corpus checks:

- one document per canonical module
- canonical bytes
- re-analysis of the current Semantic IR reproduces the document byte for
  byte
- the Semantic IR input exists

The report is written to `analysis/reports/behavior_report.json` with a
`corpus_sha256`.

**Pipeline.**

1. The parse step writes v1 IR and Semantic IR v2.
2. **Behavioral analysis** runs.
3. The pre-dataset stale gate runs. A behavioral document is CURRENT only
   when it was derived from the current Semantic IR (sha256), re-analysis
   reproduces it, and it validates. Documents for non-canonical modules are
   ORPHAN, and any other file there is UNMANAGED.
4. The Semantic IR gate runs.
5. The **behavior gate** runs (no override).
6. Datasets, provenance, the post-run stale gate and the manifest gate run.

`make behavior` regenerates Behavioral Semantics v1 alone, and
`make pipeline` regenerates everything.

**Data manifest (version 3).** Each module gains
`behavior {path, sha256, schema_version, identity_version, module_id, status,
derived_from {semantic_ir, semantic_ir_sha256}}`, and the manifest's
`versions` gain `behavior` and `behavior_identity`.

**Boundaries.**

- **Not in KF-DQ-009:**
  - signal, process or transitive dependency graphs and structural
    connectivity (KF-DQ-010)
  - FSM extraction, transition graphs, encodings and FSM confidence
    (KF-DQ-011)
  - synthesis-equivalent scheduling
- **What KF-DQ-009 provides for those tasks:** the process read/write
  summaries, register / next-value / state candidates and evidence.
- **Unchanged:** Semantic IR v2, v1 IR, prompts, datasets and splits.

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


## 11.4 Canonical Data Manifest

`manifests/data_manifest.json` is the single authoritative inventory of the
data repository (`scripts/core/data_manifest.py`, schema
`kritva-forge-data-manifest` version 3: version 2 (KF-DQ-008) added the
Semantic IR v2 references, see §5.2; version 3 (KF-DQ-009) added the
Behavioral Semantics v1 references, see §5.3). It is written as JSON because every
other machine manifest in the repository is JSON, the standard library
serialises it byte-deterministically (`sort_keys`), and it parses much faster
than YAML at about 0.8 MB.

| Section | Content |
|---|---|
| `schema`, `repository`, `generator`, `versions` | Manifest, identity, provenance, leakage, split and artifact schema versions, plus parser and parser version. No timestamp, host, user or PID. |
| `sources` | Every file under `raw/`, with path, sha256, size, status, role and the modules it feeds. |
| `modules` | One entry per canonical module: `module_id` (`mod1:`), primary and contributing sources, IR path / sha256 / `ir_content` (`n1:`) / `module_body` (`m1:`), prompt, RTL copy, dataset records and split. |
| `artifacts` | Every file of the managed tree, with kind, status and sha256. |
| `records` | Every dataset record: `record_id` (`r1:`), split, ip, module, `module_id`, task, prompt variant. |
| `splits` | Reference to the split manifest, schema versions, counts and `split_identity` (`sp1:`, over the sorted record/split pairs). |
| `manifests` | The role of every manifest file. |

Statuses:

- `canonical`: raw RTL and file lists used by canonical modules, plus canonical IR.
- `generated`: current pipeline outputs.
- `historical`: KF-DQ-006 historical paths.
- `deprecated`: reserved; none exist at version 1.
- `excluded`: present but not a dataset input. This covers unreferenced RTL, documentation, `raw/rtl/curated` and `.gitkeep`.

Manifest roles:

- **Authoritative:** only `data_manifest.json`.
- **Components, incorporated by reference:** the KF-DQ-005 provenance manifest, the KF-DQ-006 artifact inventory and the KF-DQ-004 split manifest.
- **Non-canonical:** `datasets/pipeline/manifest.json` (change tracking).
- **Historical:** the KF-DQ-001 migration manifests.

The manifest is derived from canonical inputs, KF-DQ-005 provenance and the KF-DQ-006 classification. It never reads a previous manifest. Generation is refused while any artifact is STALE, ORPHAN or UNMANAGED, so stale data cannot be listed and removed artifacts disappear. Identity rules are not duplicated: the manifest reuses the KF-DQ-003/004/005 identities, and a source's identity is its content sha256. The manifest does not hash itself. Ordering: sources and artifacts by path, modules by (ip, module), records by `record_id`, keys sorted.

`make check-manifest` (`data_manifest.py --check`) is the **dataset publication gate**. It recomputes the manifest and fails on any of these:

- a missing manifest
- an unsupported schema or component version
- an absolute, `..` or non-POSIX path
- a duplicate path or identity
- an invalid identity format
- a missing artifact or a hash mismatch
- a broken source, IR, prompt or record reference
- a historical/active misclassification
- a missing or unexpected entry
- an invalid KF-DQ-006 inventory
- a stored manifest that differs from the recomputation

The pipeline writes and validates the manifest after the provenance and stale-artifact gates, writes `analysis/reports/data_manifest_report.json`, and fails on any problem. `KRITVA_FORGE_ALLOW_STALE` does not bypass this gate. `make data-quality` runs every gate.

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

