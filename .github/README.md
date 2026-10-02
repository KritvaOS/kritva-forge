# Kritva Forge CI

The CI workflow is the merge gate for Kritva Forge.

## Required checks

- `Source Header Check`
- `Python Tests`
- `Kritva Forge Gate`

The final `Kritva Forge Gate` job fails if either required job fails.

Configure the GitHub repository branch/ruleset protection so that
**Kritva Forge Gate** is a required status check before merging.

GitHub Actions executes workflows from `.github/workflows/` for matching
push and pull-request events.
