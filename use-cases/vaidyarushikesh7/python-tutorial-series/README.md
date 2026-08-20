# SuperDocs for Python developers: a three part tutorial series

Runnable code for a three part series on editing real documents with the
SuperDocs API from Python. Standard library only, no pip install, no framework.

Built by **Rushikesh Vaidya** for the SuperDocs Round 2 task (Task 2, assigned
build: a three part tutorial series in one stack).

| Part | What you build | Costs |
| --- | --- | --- |
| [1. Connect and make the first edit](tutorials/part-1-first-edit.md) | A script that inserts a clause into a contract and verifies the rest of the document did not move | 1 operation |
| [2. Human review before changes apply](tutorials/part-2-review-gate.md) | An approval gate: the AI proposes with diffs, a person approves or denies, denials never land | 1 to 2 operations |
| [3. File handling and export at real sizes](tutorials/part-3-files-and-export.md) | A 55 page tender response uploaded, edited by chunk, exported to docx, pdf and txt, with four failures handled | 1 operation |

## Quick start

```bash
export SUPERDOCS_API_KEY=sk_your_key        # from use.superdocs.app, account settings
python3 sample/make_samples.py --big 55     # build the sample documents
python3 part1_first_edit/first_edit.py      # part one, about 20 seconds
```

Requires Python 3.10 or newer. Nothing else.

## What it looks like when it runs

Part one, verbatim, on a real account:

```
account   c5e0bfdc  tier free  500 of 500 operations left
session   session_init_299271d8cf6b
editing   (a quiet wait here is the model working, not a hang)
charged   1 operation, 500 left
summary   2 sections edited, 1 added, rest untouched

added     ['4. Confidentiality']
unchanged 4 of 5 original sections kept their text exactly
changed   ['3. Charges and payment']
table     5 rows before, 5 after
table     attributes changed on the round trip: {' border="1" cellpadding="6" cellspacing="0"'} -> {''}
PLACEMENT ['3. Charges and payment']   <-- new content landed inside this section,
          between its heading and its own text
```

The last two lines are the point of the whole series. The API reported "rest
untouched" and the document disagreed. Part two is the fix.

Part three, on a 55 page tender response:

```
upload    tender-response.docx is 0.04 MB, inline limit is 21 MB
upload    ticket 31312e09452945d59c1d50859788f396, PUT url valid 300s
upload    bytes are in storage, 2.3s, and never went through the API
parsed    412 chunks via the presigned path, parsing is not billable
edit      done, 1 operation, 4 section diff(s) returned
edit      response carried 5,164 chars of diffs instead of the whole document
export    tender-response.edited.pdf 0.40 MB, link valid 900s
check     the new data protection wording is present in the export
```

## What SuperDocs features it uses

| Feature | Where |
| --- | --- |
| `POST /v1/chat`, synchronous section-level editing | Part 1 |
| `POST /v1/sessions/init`, sessions holding a document across turns | All three |
| `GET /v1/agents/whoami`, tier and operations remaining | All three |
| `POST /v1/chat/async` with `approval_mode="ask_every_time"` | Part 2 |
| `GET /v1/jobs/{job_id}`, polling and `metadata.pending_changes` | Parts 2 and 3 |
| `POST /v1/chat/{session_id}/approve`, per change and batch decisions with feedback | Part 2 |
| `POST /v1/chat/{session_id}/continue`, answering a large-edit pause | Part 3 |
| `POST /v1/uploads` and `/v1/uploads/{id}/process`, pre-signed upload and chunked parsing | Part 3 |
| `POST /v1/documents/upload-base64`, inline upload for small files | Part 3 |
| `response_mode="compact"`, per section diffs instead of the whole document | Part 3 |
| `POST /v1/documents/export` and `POST /v1/downloads`, docx, pdf and txt | All three |
| `POST /v1/documents/export/email-request`, fallback for large exports | Part 3 |

## Layout

```
superdocs/__init__.py            the whole client, standard library only
part1_first_edit/first_edit.py   one edit, then the checks that verify it
part2_review/review_gate.py      chat_async plus the approval gate
part3_files_export/              pre-signed upload, compact mode, exports, failures
sample/make_samples.py           generates every document used, all invented
tutorials/                       the three tutorials
out/                             what the scripts write. Not in git.
```

## What the series covers

- Auth, sessions and the operation model, including where the real usage number
  lives when an account is on a promotional allowance
- Making a targeted edit and then **proving** it landed where you asked, which is
  how both of the API issues in `FINDINGS.md` were caught
- `chat_async` with `approval_mode="ask_every_time"`: pending changes, per change
  and batch decisions, feedback and revision, and an audit log
- Why an approval loop needs a stopping rule of its own
- Pre-signed uploads, the ~32 MB gateway limit, and why the error arrives as HTML
- `response_mode="compact"`: 5 KB of diffs instead of 183 KB of document
- Signed download URLs, the email fallback for large exports, and four real
  failures with the handling each one needs

## A note on the data

Every company, contract, person and number in `sample/` is invented. Northwind
Facilities Group and Harbour Lane Analytics do not exist. Nothing in this
repository contains real client material, and no API key is committed: the
scripts read `SUPERDOCS_API_KEY` from the environment and nowhere else.

## Findings

Two API issues and several rough edges were found while writing this. They are
written up in [FINDINGS.md](FINDINGS.md) with reproduction steps, in the shape
SuperDocs asks bug reports to take.

## Links

- Public repository: https://github.com/vaidyarushikesh7/superdocs-python-tutorials
- The three tutorials are in `tutorials/` in this folder and in that repository.

## License

MIT. See [LICENSE](LICENSE).

---

Built by Rushikesh Vaidya for the SuperDocs Round 2 task, August 2026.
