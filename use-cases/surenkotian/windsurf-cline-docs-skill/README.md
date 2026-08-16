# Windsurf / Cline docs skill

Built by Suren Kotian for the SuperDocs Founding Engineer task.

A dual-host package teaching Windsurf and Cline to route document edits (`.docx`, `.pdf`, `.html`) through SuperDocs' MCP tools before touching the file directly -- each half written natively for its own host's real file layout, not a shared shim.

## What's in each half

```
windsurf/
  .windsurf/rules/superdocs-docs.md   -- workspace rule (YAML frontmatter: trigger: model_decision)
  mcp_config.snippet.json             -- merges into ~/.codeium/windsurf/mcp_config.json
cline/
  .clinerules/superdocs-docs.md       -- workspace rule (plain markdown, no frontmatter)
  cline_mcp_settings.snippet.json     -- merges into VS Code's global storage for the Cline extension
install.py                             -- safe merge installer for either host (see below)
```

Both rule files teach the identical behavior -- upload through SuperDocs, edit via `chat`/`chat_async`, respect Review-mode `pending_changes`, export back to the original format -- but each is written in that host's own native rule format, because the formats are genuinely different (Windsurf requires YAML frontmatter with a `trigger` field; Cline's docs are explicit that rules are "no special syntax, schema, or required structure," just markdown).

## Installing

**Windsurf:**
```bash
python install.py windsurf              # merges the superdocs MCP entry into your global config
cp -r windsurf/.windsurf <your-project>/  # copies the workspace rule into your project
export SUPERDOCS_API_KEY=sk_...          # the config references this via ${env:SUPERDOCS_API_KEY}
```

**Cline (VS Code extension):**
```bash
python install.py cline
cp -r cline/.clinerules <your-project>/
export SUPERDOCS_API_KEY=sk_...
```

`install.py` **merges**, it does not overwrite -- both target files are global (shared across every workspace the host has open), so it loads the existing file, adds/updates only the `superdocs` key under `mcpServers`, backs up the original to `<file>.bak`, and is idempotent (a second run with nothing changed is a no-op, verified below). Use `--dry-run` to see exactly what it would write without touching anything.

## What's actually verified here, and what isn't -- honestly

**Verified for real:**
- The SuperDocs MCP server itself: a real JSON-RPC `initialize` handshake against `https://api.superdocs.app/mcp` with a live API key, which returned `serverInfo: {"name": "SuperDocs", "version": "3.4.0"}` and its real capabilities/instructions (see `mcp_handshake_proof.json`).
- The installer's merge logic: tested against a temp config file containing an unrelated pre-existing MCP server, confirmed the existing server survives, confirmed idempotency on a second run, confirmed a `.bak` file is written (`test_install.py`).
- Every config field name and file path against each host's real, current documentation and source-linked GitHub issues -- not memory. This mattered more than expected: Windsurf's own docs domain now redirects to `docs.devin.ai` (Cognition, makers of Devin, appear to have absorbed Windsurf since this task brief was written) -- `.windsurf/rules/` is confirmed still live as the documented "legacy fallback" path, which is what let this build follow the task brief's naming exactly. Separately, the MCP server's own `initialize` response advertises a skill guide at `docs.superdocs.app/skill.mdx` -- that URL 404s; the real path is `skill.md` (reported in the task submission's bug list).

**Not verified:** actually opening a real Windsurf workspace or VS Code+Cline session and watching a live chat request route through the MCP tool calls end to end. VS Code and the Cline extension are genuinely installed in this environment (`saoudrizwan.claude-dev` v4.1.5) and I confirmed the extension is present, but driving its chat UI and observing tool-call behavior needs GUI interaction this environment doesn't have. I also deliberately did not run the installer against this machine's *real* global Cline/Windsurf config non-interactively -- both are live application state outside this repo, on a real development machine, and overwriting them (even with a safe merge) isn't something to do unilaterally without the machine's owner running it themselves. The merge logic is proven correct against an isolated temp file instead (see `test_install.py`), which verifies the same code path without touching real system state.

## Real MCP handshake proof

`mcp_handshake_proof.json` is the actual response from `https://api.superdocs.app/mcp` to a real `initialize` call, captured while building this.
