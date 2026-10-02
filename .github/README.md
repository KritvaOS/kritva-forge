# Kritva Forge CI

The `forge-ci.yml` workflow is the repository commit/merge gate.

The protected default branch should require the **Kritva Forge Gate** status
check. The gate succeeds only when source-header validation and the Python test
job both succeed.

The workflow does not require the private `kritva-forge-data` repository.
Public CI tests code and infrastructure only.
