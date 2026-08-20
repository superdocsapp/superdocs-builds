"""
Synthesize a deliberately BREAKING revision of the current spec, to demonstrate
that the compatibility gate catches breaking changes and fails CI.

The real published history (old a8351de -> new ac0d44c) is backward-compatible
(only additions), which is the correct, authentic result. This script derives a
hypothetical "next" spec from the NEW spec by applying three controlled deltas —
each a classic breaking change — so we can prove the gate flags them:

  1. remove an existing endpoint          (clients calling it now 404)
  2. make an optional parameter required   (existing clients omit it -> 400)
  3. narrow a parameter's type             (string -> integer: old values rejected)

It prints exactly what it changed. Output: specs/superdocs-breaking.json
"""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW = os.path.join(HERE, "specs", "superdocs-new.json")
OUT = os.path.join(HERE, "specs", "superdocs-breaking.json")

spec = json.load(open(NEW, encoding="utf-8"))
spec = json.loads(json.dumps(spec))  # deep copy
paths = spec["paths"]
changes = []

_METHODS = ("get", "post", "put", "delete", "patch")

# 1) Remove an endpoint (prefer a well-known one so the report reads clearly).
for candidate in ["/v1/documents/export", "/v1/chat/{session_id}/approve",
                  "/v1/documents/upload", "/v1/chat"]:
    if candidate in paths:
        del paths[candidate]
        changes.append(f"removed endpoint {candidate}")
        break

# 2) Make the first optional parameter we find required.
def _first_optional_param():
    for p, item in paths.items():
        for m, op in item.items():
            if m not in _METHODS or not isinstance(op, dict):
                continue
            for param in op.get("parameters", []):
                if not param.get("required", False):
                    return p, m, param
    return None, None, None

p, m, param = _first_optional_param()
if param is not None:
    param["required"] = True
    changes.append(f"made parameter '{param.get('name')}' required on {m.upper()} {p}")

# 3) Narrow a string parameter's type to integer.
def _first_string_param():
    for p, item in paths.items():
        for m, op in item.items():
            if m not in _METHODS or not isinstance(op, dict):
                continue
            for param in op.get("parameters", []):
                if param.get("schema", {}).get("type") == "string":
                    return p, m, param
    return None, None, None

p, m, param = _first_string_param()
if param is not None:
    param["schema"]["type"] = "integer"
    changes.append(f"narrowed type of '{param.get('name')}' (string->integer) on {m.upper()} {p}")

json.dump(spec, open(OUT, "w", encoding="utf-8"), indent=2)
print(f"Wrote {os.path.relpath(OUT, HERE)} with {len(changes)} breaking delta(s):")
for c in changes:
    print("  -", c)
