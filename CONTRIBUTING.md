# Contributing to Kritva Forge

Contributions should preserve the separation between parsing, RTL IR, semantic analysis, structural analysis, FSM analysis, dataset generation, and AI/LLM tooling.

Do not contribute proprietary RTL or restricted datasets to the public repository.

## Local Development

The standard setup uses a sibling private data repository:

```text
~/workarea/kritvaos/
├── kritva-forge/
└── kritva-forge-data/
```

Initialize the environment and run the gates:

```bash
make setup
make headers
make test
```

Run the RTL pipeline against the private data repository:

```bash
make pipeline
```

Override the data repository if required:

```bash
make pipeline DATA_ROOT=/path/to/kritva-forge-data
```

## Source Header Validation

```bash
make headers
```


## Continuous Integration Gate

Every pull request and push to the protected branches is validated by the
Kritva Forge CI workflow.

The required gates are:

1. **Source Header Check**
2. **Python Tests**
3. **Kritva Forge Gate**

The repository maintainers should configure the `Kritva Forge Gate` check as a
required status check for the protected `main` branch.

Local equivalent:

```bash
python3 scripts/lint/check_source_headers.py --mode all --strict
python3 tests/lint/test_source_headers.py
python3 -m pytest -q
```
