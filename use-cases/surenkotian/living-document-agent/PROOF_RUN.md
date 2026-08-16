# Proof run, real terminal output, real API, real account

Account created via `POST /v1/agents/signup` (self-signup flow documented at docs.superdocs.app), free tier, 500 ops/month. Every call below is real; nothing in this file is a description of expected behavior.

## 1. Bootstrap (first run, no document exists yet)

```
$ python living_doc_agent.py --source source_data/status_v1.json
[living-doc-agent] no existing document in state -- creating the standing document for the first time
[living-doc-agent] create response: I have created the 'Team Operations Dashboard' document with the priorities, notes, and service status table as requested.
[living-doc-agent] created document b3faf2bc-f5da-4cb5-91f4-6609cf34d9d6, owned section = 2 chunk(s): ['e756e234-b5fe-4f98-b12f-5191015f2f89', '411f0464-77eb-4220-98b6-69e5f08de603']
[living-doc-agent] bootstrap complete. Re-run with a changed --source file to see an update cycle.
```

Resulting document (fetched via `GET /v1/documents/{id}?include_html=true` immediately after):

```html
<h1 data-chunk-id="ef20f84f-a3e9-4149-86cb-d52ed76cb45d">Team Operations Dashboard</h1>
<h2 data-chunk-id="84d98a95-db3d-45c9-ad20-5f0b92a301ee">Weekly Priorities</h2>
<ol data-chunk-id="b34ba260-9486-472e-9673-c2e4b53b5ca3"><li>Ship the Q3 customer portal redesign.</li><li>Close out vendor renewal negotiations before end of month.</li><li>Onboard two new SRE hires.</li></ol>
<h2 data-chunk-id="9267d12f-8918-4ee6-adba-3f5030b64bd6">Team Notes</h2>
<p data-chunk-id="da73c3db-6086-4285-90cc-a42d6721b7b7">Standup moved to 9:15am starting Monday. Ping Priya if you're out.</p>
<h2 data-chunk-id="e756e234-b5fe-4f98-b12f-5191015f2f89">[AGENT-MAINTAINED] Live Service Status -- do not edit manually</h2>
<table data-chunk-id="411f0464-77eb-4220-98b6-69e5f08de603"><thead><tr><th>Service</th><th>Status</th><th>Latency</th></tr></thead><tbody><tr><td>API Gateway</td><td>Operational</td><td>42ms</td></tr><tr><td>Auth Service</td><td>Operational</td><td>55ms</td></tr><tr><td>Billing Worker</td><td>Operational</td><td>120ms</td></tr><tr><td colspan="3">Last synced: 2026-08-01T09:00:00Z</td></tr></tbody></table>
```

## 2. Real update cycle (Auth Service degrades)

```
$ python living_doc_agent.py --source source_data/status_v2.json --auto-approve
[living-doc-agent] source changed: b13ccd3f7584... -> f1b8a999b9f8...
[living-doc-agent] submitted job 27dcfc01-052a-4459-8612-e90edf2b1a57, polling...
[living-doc-agent] approved 1 change(s), all confirmed scoped to the owned section
[living-doc-agent] boundary check passed: all 5 chunks outside the owned section are byte-identical before/after
[living-doc-agent] update complete
```

Document afterward -- only the table's own chunk_id (`411f0464-...`) changed; every other chunk_id and its content is byte-identical to step 1:

```html
<h1 data-chunk-id="ef20f84f-a3e9-4149-86cb-d52ed76cb45d">Team Operations Dashboard</h1>
<h2 data-chunk-id="84d98a95-db3d-45c9-ad20-5f0b92a301ee">Weekly Priorities</h2>
<ol data-chunk-id="b34ba260-9486-472e-9673-c2e4b53b5ca3">...same three items, unchanged...</ol>
<h2 data-chunk-id="9267d12f-8918-4ee6-adba-3f5030b64bd6">Team Notes</h2>
<p data-chunk-id="da73c3db-6086-4285-90cc-a42d6721b7b7">Standup moved to 9:15am starting Monday. Ping Priya if you're out.</p>
<h2 data-chunk-id="e756e234-b5fe-4f98-b12f-5191015f2f89">[AGENT-MAINTAINED] Live Service Status -- do not edit manually</h2>
<table data-chunk-id="411f0464-77eb-4220-98b6-69e5f08de603"><thead><tr><th>Service</th><th>Status</th><th>Latency</th></tr></thead><tbody><tr><td>API Gateway</td><td>Operational</td><td>45ms</td></tr><tr><td>Auth Service</td><td>Degraded</td><td>890ms</td></tr><tr><td>Billing Worker</td><td>Operational</td><td>118ms</td></tr><tr><td colspan="3">Last synced: 2026-08-01T15:00:00Z</td></tr></tbody></table>
```

## 3. Stopping rule / non-self-retriggering, proven with `whoami`, not asserted

```
$ curl -s https://api.superdocs.app/v1/agents/whoami -H "Authorization: Bearer $KEY" | grep used
"used":6

$ python living_doc_agent.py --source source_data/status_v2.json --auto-approve
[living-doc-agent] source unchanged (hash f1b8a999b9f8...) -- nothing to do, no API call made

$ curl -s https://api.superdocs.app/v1/agents/whoami -H "Authorization: Bearer $KEY" | grep used
"used":6
```

The agent's own edit in step 2 changed the document. Re-running against the *same source* immediately afterward did not treat that change as new work, because the stopping condition is keyed to the external source hash, never to the document's own state. `used` is bit-for-bit identical before and after.

## 4. Second real update (recovery)

```
$ python living_doc_agent.py --source source_data/status_v3_recovered.json --auto-approve
[living-doc-agent] source changed: f1b8a999b9f8... -> 10d49247d030...
[living-doc-agent] submitted job 7defca5e-968f-4601-a8c7-e4034d37a40e, polling...
[living-doc-agent] approved 1 change(s), all confirmed scoped to the owned section
[living-doc-agent] boundary check passed: all 5 chunks outside the owned section are byte-identical before/after
[living-doc-agent] update complete
```

## 5. No-spend preview mode, proven with `whoami`

```
$ curl -s .../whoami | grep used
"used":7

$ python living_doc_agent.py --source source_data/status_v2.json --preview
[living-doc-agent] source changed: 10d49247d030... -> f1b8a999b9f8...
[living-doc-agent] PREVIEW MODE (no-spend): the following would be sent, but no chat call is made:
----------------------------------------------------------------------
In the section headed exactly "[AGENT-MAINTAINED] Live Service Status -- do not edit manually", replace the existing table ENTIRELY with a new table matching the following description...
----------------------------------------------------------------------
[living-doc-agent] preview complete -- 0 operations spent (verify with whoami)

$ curl -s .../whoami | grep used
"used":7
```

## 6. `agent_state.json` run_history, a readable history, not churn

```json
[
  {"timestamp": "2026-08-06T16:08:21Z", "action": "created", "document_id": "b3faf2bc-..."},
  {"timestamp": "2026-08-06T16:09:00Z", "action": "updated", "source_hash": "f1b8a999...", "boundary_verified": true},
  {"timestamp": "2026-08-06T16:09:22Z", "action": "noop", "source_hash": "f1b8a999..."},
  {"timestamp": "2026-08-06T16:10:09Z", "action": "updated", "source_hash": "10d49247...", "boundary_verified": true}
]
```

Four entries for four runs against three distinct source states plus one repeat, not four full-document rewrites.

## The bug this proof run actually caught

The *first* attempt at step 2 (against a document created before the table/paragraph redesign described in README.md) produced this, verbatim, from the live API:

```html
<table data-chunk-id="57c00e34-...">...(correctly updated table)...</table><p>Last synced: 2026-08-01T15:00:00Z</p>
<p data-chunk-id="78c828e9-...">Last synced: 2026-08-01T09:00:00Z</p>
```

Two "Last synced" lines. The new one has **no `data-chunk-id` at all**, it was inserted as fresh content, not an edit to the existing paragraph, which the old one still was. The boundary-diff code itself also had a bug at this point (it only checked chunks present in both before/after snapshots, so an *added* chunk outside the section didn't register as a detected change in the log message, even though the raw equality check correctly still failed the run). Both are fixed in the shipped version. The table now carries its own timestamp as a spanning row, and the diff check now reports added/removed/changed separately. Re-run afterward (step 2 above) is the fixed, clean result.
