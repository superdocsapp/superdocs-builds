# Add a fourth framework binding

A new binding should translate the portable `ToolSpec`; it should not reimplement any
SuperDocs operation.

## Process

1. Add the framework SDK as an optional dependency in `pyproject.toml`.
2. Create `src/superdocs_adapter/bindings/<framework>.py`.
3. Import the SDK only inside that binding module or its factory functions.
4. Convert every value returned by `SuperDocsToolset.specs()` into the framework's
   native tool type.
5. Delegate execution to `spec.handler`; do not add HTTP or polling code.
6. Provide an `invoke(toolset, arguments)` helper that crosses the native framework
   tool boundary without requiring an extra LLM call.
7. Add the smallest native workflow/agent constructor that makes the framework shape
   visible without moving core behavior into the binding.
8. Copy a quickstart directory and change only the binding import and output path.
9. Add the binding to `tests/test_binding_parity.py` and `test_framework_shapes.py`.
10. Prove that importing the core still does not import the new framework.
11. Run clean-clone checks and, once, the opt-in live parity test.
12. Update the compatibility table, changelog, and semantic version.

## Binding contract

Given the portable schema:

```python
spec = toolset.specs()[0]
```

the binding must preserve:

- `spec.name`
- `spec.description`
- Required parameter names and meanings
- Allowed export formats
- The dictionary returned by `spec.handler`
- Exceptions from the core unless the framework requires a documented wrapper
- Checkpoint and recovery behavior through `spec.handler`

## Definition of done

- Importing `superdocs_adapter` does not import the new framework.
- The core installs without the new optional extra.
- The native tool can be attached to an agent in that framework.
- The quickstart runs from a clean clone.
- Its canonical result and export match all existing bindings.
- Re-running it adopts its checkpoint rather than repeating the edit.
- The package builds successfully as both wheel and source distribution.
