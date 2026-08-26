# Image generation billing (live SuperDocs docs, Phase 2 / Prompt 7)

**Checked:** 18 August 2026  
**Sources:**
- [Plans & Usage](https://docs.superdocs.app/account/plans-and-usage.md)
- [Attachments](https://docs.superdocs.app/concepts/attachments.md)
- [Agent Editing Playbook — Operations and billing](https://docs.superdocs.app/guides/agent-editing-playbook.md)
- MCP tool `upload_image_base64` (hosting a stable embed URL)

## Finding

**AI image generation is not a separate billable product / SKU on this platform.**  
It rides a normal **document-edit `chat` operation**.

| Path | Billable? | Notes |
|---|---|---|
| Chat: “generate an image of …” and insert into the document | **Yes — as a chat/edit operation** (typically 1 op; large multi-section edits may bill 1 per 25 sections) | Same pool as other AI edits. Listed under AI actions that modify documents. |
| `upload_image_base64` / upload image → stable URL | **Not listed as an AI operation** | Hosting / embed URL. Like opening the editor or exporting — not in the “what counts as an operation” list. |
| Pure URL swap of an existing image in the doc | **No AI generation cost** (docs say so explicitly) | “Swap an image… — pure URL swap, no AI generation cost” ([Attachments](https://docs.superdocs.app/concepts/attachments.md)). |
| Export / download | **0 ops** | Confirmed elsewhere; unchanged. |

## Implication for this build

- Budget **image-bearing sections as chat ops**, not a distinct image line item.
- Prefer: generate/insert via a targeted chat on an `image_eligible` section (still subject to the 2-section batch cap when batched with other edits), **or** upload a prepared image URL then ask chat to embed it (upload itself should not consume the edit budget; the embed chat does).
- Do **not** assume image generation is free. Do **not** invent a per-image surcharge beyond what Plans & Usage states.
- Confirm remaining quota from the `usage` block on chat responses (`ops_charged`, `monthly_remaining`).

## What we did not find

No account-tier table that prices “image generation” separately from document-edit operations for Free / Plus / Pro. Plans differ by **operation volume**, not by feature (full access to web, REST, MCP, and model tiers on all plans).
