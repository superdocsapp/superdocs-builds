# Task contract

## Scope

Build one framework-independent SuperDocs adapter and three thin, comparable
quickstarts for agent developers. The required SuperDocs lifecycle is upload, edit,
approve, and export.

## Must do

- Keep the core free of framework dependencies.
- Use native LangGraph, CrewAI, and OpenAI Agents tool shapes.
- Produce identical output for the same task.
- Run from a clean clone.
- Explain direct hosted MCP versus a wrapper.
- Make a fourth binding an isolated translation task.
- Version releases.
- Parse proposed-change JSON strings exactly once beyond the response parse.
- Treat long-running jobs as processing and bound operation-spending tests.

## Must never do

- Write credentials, document bodies, or proposed content to checkpoints or logs.
- Repeat a costly edit merely because polling or export failed.
- Put framework code in the client, adapter, or portable tool specification.
- Claim DOCX/PDF byte identity when only normalized text was compared.
- Run live parity without explicit opt-in.
- Modify files outside `extensions/vrutansh/superdocs-agent-adapter/`.

## Definition of done

- Offline tests pass without a live key.
- Three native framework quickstarts share one core and one task.
- Mock and live parity tests prove identical exported content.
- Restart tests prove upload/edit work is not duplicated across durable boundaries.
- Large inputs use the pre-signed streaming path.
- Errors name the cause and a recovery action.
- README, architecture, trade-offs, fourth-binding guide, and limitations are current.
- Wheel and source distribution build from a clean copy.
- Ruff lint/format checks and the 90% coverage floor pass.
- `v0.1.0` is tagged and the public pull request targets the `extensions` folder.
