# Progress and evidence

## Assumptions

- REST is the core transport because every Python framework can use HTTP and the
  approval/job/export lifecycle is straightforward to contract-test.
- Quickstart parity should not depend on three separate agent planners or provider
  keys; native tool execution isolates the adapter behavior being compared.
- TXT is the canonical parity format because it supports stable content comparison.
- One unique session belongs to one high-level edit operation.

## Verified

- Public base commit: `bff5512`.
- Windows/Python 3.12.10: 9 original offline tests passed; 91% coverage.
- Windows live parity: LangGraph, CrewAI, and OpenAI Agents matched the expected
  export in the original 52.63-second small-document run and the final hardened
  70.93-second run.
- Linux/Python 3.12.13 hardening suite: 31 offline tests pass; 91% branch coverage.
- Wheel and source distribution build successfully.
- Clean-copy install, lint, format, 31-test coverage run, and package build passed after
  hardening in an isolated directory.

## Hardening added after the public base commit

- Atomic non-secret checkpoints and input fingerprints.
- Recovery of an accepted job through the unique session history.
- Completed-job re-entry that repeats only free export.
- Automatic pre-signed streaming upload above 20 MiB.
- Native StateGraph, CrewAI Flow, and OpenAI Agent structures.
- Explicit CrewAI telemetry suppression for the local comparison.
- Actionable failure messages and recovery tests.

## Still required before pull request

- Commit and push the verified Windows changes and screenshot.
- Tag `v0.1.0` and publish release notes.
- Add the final demo URL.
- Open the upstream pull request with name and project summary.
