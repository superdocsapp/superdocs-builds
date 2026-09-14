"""One-off, real-API verification script - not part of the test suite (which stays offline/fake per the
round's own standard). This is the single most important check in this whole build: whether SuperDocs's
real product actually preserves a code block and a diagram reference through a markdown round-trip, which
the fake client's byte-identical-passthrough tests cannot prove either way.
"""

import os

from app.guide_generator import generate_getting_started_guide
from app.markdown_roundtrip import round_trip_markdown
from app.superdocs_client import RealSuperDocsClient

SAMPLE_MARKDOWN = """# API Reference: createWidget

Creates a new widget.

```python
import widgets

client = widgets.Client(api_key="...")
result = client.create_widget(name="my-widget")
```

Architecture:

![sequence diagram](./diagrams/create-widget-flow.png)
"""

api_key = os.environ.get("SUPERDOCS_API_KEY")
if not api_key:
    raise SystemExit("SUPERDOCS_API_KEY not set")

client = RealSuperDocsClient(api_key)

print("=== Mode 1: markdown round-trip fidelity (the biggest unverified risk in this build) ===")
result = round_trip_markdown(client, SAMPLE_MARKDOWN, session_id="roundtrip-verify-1")
print("code_blocks_preserved:", result.code_blocks_preserved)
print("image_refs_preserved:", result.image_refs_preserved)
print()
print("--- original code blocks ---")
for cb in result.original_code_blocks:
    print(repr(cb))
print("--- round-tripped code blocks ---")
for cb in result.round_tripped_code_blocks:
    print(repr(cb))
print()
print("--- original image refs ---")
print(result.original_image_refs)
print("--- round-tripped image refs ---")
print(result.round_tripped_image_refs)
print()
print("--- full round-tripped markdown ---")
print(result.round_tripped_markdown)
print()

print("=== Mode 2: getting-started guide generation ===")
guide = generate_getting_started_guide(
    client,
    "Sign up for a free account at example.com. Create an API key in Settings. "
    "Install the SDK with pip install widgets-sdk. Call client.create_widget() to make your first widget.",
    session_id="guide-verify-1",
)
print(guide)

client.close()
