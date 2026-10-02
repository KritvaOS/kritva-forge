# Kritva Forge Data

The public `kritva-forge` repository is code-only. Runtime RTL, normalized IR,
analysis artifacts, golden data, prompts, and datasets belong in the private
`KritvaOS/kritva-forge-data` repository.

Expected local layout:

```text
~/workarea/kritvaos/
├── kritva-forge/
└── kritva-forge-data/
    ├── raw/rtl/
    ├── normalized/ir/
    ├── analysis/
    ├── golden/
    ├── generated/
    ├── datasets/
    ├── splits/
    └── manifests/
```

The Makefile defaults to the sibling data repository:

```bash
make pipeline
```

Override it when needed:

```bash
make pipeline DATA_ROOT=/path/to/kritva-forge-data
```

The public repository must not contain proprietary RTL, private datasets,
generated golden corpora, model checkpoints, or restricted training data.

## Canonical normalized IR layout (KF-DQ-001)

```text
normalized/ir/<ip>/
├── hierarchy.yaml
├── summary.yaml
├── modules/
│   └── <module>.yaml      # the only canonical module representation
└── rtl/                   # RTL copies; location to be revisited in KF-DQ-006
```

Consumers must enumerate module IR with
`scripts.core.paths.iter_module_yamls()`; any other `*.yaml` directly under
`<ip>/` is non-canonical. Check a data checkout with:

```bash
make check-layout
make test-data
```

