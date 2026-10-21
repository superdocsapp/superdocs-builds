# Slack thread → meeting minutes

*Built by Arun S for the SuperDocs Round-2 task.* (Open-list family: **Integrations and pipelines**.)

A flow that **starts in another tool and ends in an exported document**: point it at a Slack thread,
it structures the conversation into **attendees, decisions, and action items** (with @owners), then
hands branded minutes to SuperDocs to export a `.docx`.

```
Slack thread --> {attendees, decisions, action items, discussion} --> HTML --> SuperDocs --> .docx
```

## Run it (offline, no token)
```bash
python run_demo.py            # structures the sample thread and prints the minutes HTML
python -m pytest tests/ -q    # 3 keyless tests (incl. the full Slack->export pipeline with fakes)
```
Sample output: decisions `keep pricing unchanged`, `launch Aug 20`; actions `@arun checklist`, `@meera FAQ`.

## Run it live (what you provide)
A Slack **bot token** with `channels:history` (and `groups:history` for private channels), plus a
channel id + thread timestamp:
```bash
SLACK_TOKEN=xoxb-... SUPERDOCS_API_KEY=... python -c \
 "from slack import Slack; from superdocs_min import SuperDocs; from minutes import export_minutes; \
  print(export_minutes(Slack(), SuperDocs(), 'C0123', '1699999999.000100')['structured'])"
```

## Files
| File | What it is |
|---|---|
| `slack.py` | Minimal Slack `conversations.replies` client; injectable transport for tests. |
| `minutes.py` | Structure messages → decisions/actions/attendees → minutes HTML → SuperDocs export. |
| `superdocs_min.py` | The SuperDocs hand-off (send + export). |
| `sample_thread.json`, `run_demo.py`, `tests/` | Offline sample + demo + keyless tests. |

Extraction is keyword-cued and deterministic (keyless); a model-based classifier is the drop-in
upgrade for messier threads. **Where it goes:** a PR into the public repo, **use-cases** folder.
