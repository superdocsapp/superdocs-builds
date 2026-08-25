# CI workflow hand-off

This project keeps its CI workflow definitions in its own submission folder to
follow this repository's contribution rule: project work must not modify files
outside `extensions/oviya12/doctask2-oviya-senthilkumar/`.

GitHub Actions only discovers workflows at the repository root,
`.github/workflows/`. Therefore, a repository maintainer who wants to enable
these workflows should copy the definitions below to that directory after
reviewing the requested permissions and registry credentials:

- `client-pipeline.yml`: runs regeneration, the compatibility gate, and smoke
  tests for pull requests and pushes that change this project.
- `refresh-and-publish-clients.yml`: a weekly spec refresh and publish flow.
  It requires `PYPI_API_TOKEN` and `NPM_TOKEN` repository secrets and the
  repository's approval for a workflow that commits refreshed specs/reports.

The application pipeline itself remains fully runnable locally with
`make all` or `bash scripts/pipeline.sh`.
