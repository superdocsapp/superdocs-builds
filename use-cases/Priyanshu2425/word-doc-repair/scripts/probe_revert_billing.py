"""Is a native revert billable? Read the number, do not assume it.

Spends exactly one operation on purpose: the chat turn that creates something
to revert. Everything else is expected to be free, and whether it is happens to
be the whole question.
"""
import json, os, sys, time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "backend"))
from docrepair.superdocs_client import resolve_superdocs  # noqa: E402

# The same resolver the product uses, rather than a second copy of the base
# and a key read straight off disk. A probe that reaches a different endpoint
# than the thing it is probing measures the wrong endpoint -- and the numbers
# below are only worth reading if they came from where the app goes.
#
# The agent-credentials file stays as the last resort: this script predates
# both `.env` and the relay, and somebody running it on a machine set up that
# way should not have to configure anything twice.
_endpoint = resolve_superdocs()
if _endpoint.available:
    BASE, KEY = _endpoint.base_url, _endpoint.api_key
else:
    BASE = "https://api.superdocs.app"
    KEY = json.load(open(os.path.expanduser(
        "~/.superdocs/agent_credentials.json")))["api_key"]
H = {"Authorization": f"Bearer {KEY}"}
DOC = sys.argv[1]
SID = f"revert-billing-probe-{int(time.time())}"

log = []
def bal(label):
    r = requests.get(f"{BASE}/v1/agents/whoami", headers=H, timeout=30)
    q = (r.json() or {}).get("quota") or {}
    n = q.get("remaining")
    log.append((label, n))
    print(f"  balance after {label:<22} = {n}")
    return n

print("session:", SID, "\ndoc:", DOC, os.path.getsize(DOC), "bytes\n")
start = bal("start")

print("\n[1] upload (docs say free)")
with open(DOC, "rb") as fh:
    r = requests.post(f"{BASE}/v1/documents/upload", headers=H,
                      files={"file": (os.path.basename(DOC), fh)},
                      data={"session_id": SID}, timeout=300)
print("   ", r.status_code)
r.raise_for_status()
after_upload = bal("upload")

print("\n[2] one chat turn (expected: 1 operation)")
r = requests.post(f"{BASE}/v1/chat", headers=H, timeout=300, json={
    "session_id": SID,
    "message": ("Formatting only. Make every heading one step smaller. Do NOT add, "
                "remove, expand, summarise, complete or reword any text."),
})
print("   ", r.status_code)
r.raise_for_status()
body = r.json()
print("    usage:", json.dumps(body.get("usage"), indent=None))
after_chat = bal("chat turn")

print("\n[3] history -> turn_index of the user message")
r = requests.get(f"{BASE}/v1/sessions/{SID}/history", headers=H, timeout=60)
print("   ", r.status_code)
r.raise_for_status()
msgs = (r.json() or {}).get("messages") or []
for m in msgs:
    print(f"     turn_index={m.get('turn_index')} role={m.get('role')} "
          f"checkpoint_id={'set' if m.get('checkpoint_id') else 'null'}")
user_turns = [m for m in msgs if m.get("role") == "user" and m.get("checkpoint_id")]
after_history = bal("history read")

if not user_turns:
    print("\nNo revertable user message. Stopping before revert.")
    sys.exit(0)

ti = user_turns[-1]["turn_index"]
print(f"\n[4] revert to turn_index={ti}  <-- THE QUESTION")
r = requests.post(f"{BASE}/v1/sessions/{SID}/revert", headers=H,
                  json={"turn_index": ti}, timeout=120)
print("   ", r.status_code)
if r.status_code < 400:
    rb = r.json()
    print("    reverted_to_turn:", rb.get("reverted_to_turn"),
          "| archived_turn_count:", rb.get("archived_turn_count"))
    print("    compose_text:", repr((rb.get("compose_text") or "")[:70]))
    print("    redo_checkpoint_id:", "set" if rb.get("redo_checkpoint_id") else "absent")
    print("    usage in response:", rb.get("usage"))
else:
    print("    body:", r.text[:400])
after_revert = bal("REVERT")

print("\n[5] redo (undo the undo)")
r = requests.post(f"{BASE}/v1/sessions/{SID}/redo", headers=H, json={}, timeout=120)
print("   ", r.status_code, r.text[:200] if r.status_code >= 400 else "")
after_redo = bal("REDO")

print("\n" + "=" * 58)
print("VERDICT")
print(f"  upload   cost {after_upload  is not None and start        - after_upload}")
print(f"  chat     cost {after_chat    is not None and after_upload - after_chat}")
print(f"  history  cost {after_history is not None and after_chat   - after_history}")
print(f"  REVERT   cost {after_revert  is not None and after_history- after_revert}")
print(f"  REDO     cost {after_redo    is not None and after_revert - after_redo}")
print(f"  total spent this probe: {start - after_redo}")
