# Putting a human in front of every AI edit

**Part two of three. A review gate: the AI proposes, a person decides, and nothing
touches the document until someone says yes.**

[Part one](part-1-first-edit.md) ended with a problem. The edit succeeded, the
API reported "rest untouched", and the new clause had landed between another
section's heading and its own paragraph. We only knew because we checked
afterwards, and by then it was in the document.

This part fixes the order of operations. Same instruction, same document, but
every proposed change stops in front of you first.

## Prerequisites

Part one, or at least its setup: Python 3.10 or newer, `SUPERDOCS_API_KEY` in
your environment, and the sample document from `python3 sample/make_samples.py`.

## Why the synchronous call cannot do this

`POST /v1/chat` applies and then answers. There is no gap to stand in. What you
need instead is the async pair:

| Call | Role |
| --- | --- |
| `POST /v1/chat/async` with `approval_mode="ask_every_time"` | Propose, do not apply. Returns a `job_id`. |
| `GET /v1/jobs/{job_id}` | Poll. `status=awaiting_approval` means it is waiting on you, and `metadata.pending_changes` is what it wants to do. |
| `POST /v1/chat/{session_id}/approve` | Your decision, per change or as a batch. Approved changes apply atomically, denied ones are discarded. |

The job is durable server side. If your script dies mid-review, the job is still
waiting and you can poll it again.

## Start the job

```python
job_id = client.chat_async(
    session_id=session_id,
    message=INSTRUCTION,
    document_html=original,
    approval_mode="ask_every_time",
)
```

That is the only difference from part one, and it changes who is in charge.

## Poll until it wants you

```python
job = client.wait_for_job(job_id)          # stops on awaiting_approval,
status = job["status"]                     # completed, failed or cancelled
```

Polling every three seconds is plenty. The job carries a `progress` percentage,
and on a long document it will sit at 99 percent for a while before it has
anything to show you. That is normal.

## Show a person something they can judge

`metadata.pending_changes` gives you, per change, a `chunk_id`, the old HTML and
the new HTML. A reviewer cannot read HTML diffs at speed, so render the visible
text:

```python
before, after = visible_text(change.old_html), visible_text(change.new_html)
for line in difflib.unified_diff(wrap(before), wrap(after), lineterm="", n=1):
    print("  " + line)
```

Real output from `review_gate.py`:

```
========================================================================
change 2 of 4    chunk 4b506d83-e008-406c-a67c-b12439e5a154

word level diff, - is going, + is arriving:

   Service line Basis Monthly charge Planned maintenance Fixed 4,200 Reactive callout,
  -business hours Per visit 180 Reactive callout, out of hours Per visit 320 Consumables At
  +business hours Per visit 180 Reactive callout, out of hours Per visit 360 Consumables At
   cost plus 8 percent Variable
========================================================================
approve change 2/4? [y]es / [n]o / [f]eedback:
```

Three cases need different rendering, and mixing them up makes the reviewer
distrust the tool:

- **New text**, where `old_html` is empty. Show it as an addition, not a diff.
- **Deletion**, where `new_html` is empty. Say plainly that text is going.
- **No visible change**, where both sides read the same. This happens more than
  you would expect: a move, or a renumbering that came out identical. Say so,
  rather than printing an empty diff and looking broken.

## Send the decisions

One change:

```python
client.approve(session_id, job_id, approved=False, change_id=change.change_id,
               feedback="This landed inside section 3. Place it after the whole "
                        "of section 3, including its table.")
```

Several at once:

```python
client.approve(session_id, job_id, approved=any(decisions),
               changes=[{"change_id": c, "approved": True} for c in ids])
```

Then keep polling. The job resumes, and either finishes or comes back with more.

## Proof that denial is real

Run the gate and refuse everything:

```bash
python3 part2_review/review_gate.py --deny-all
```

```
final status: completed
approved 0, denied 5, audit written to out/review-audit.json
sections added: none
placement: clean
table: the out of hours charge still reads 320, so that change did not apply
```

Nothing landed. The document is byte identical to what went in. That is worth
running once yourself, because "the gate is real" is exactly the claim a reviewer
in a regulated workflow will want evidence for, and it takes one command.

## Feedback, and the loop I walked straight into

Deny with feedback and the AI revises. That is the good version:

```bash
python3 part2_review/review_gate.py --revise
```

```
change 1 of 1    chunk new
  + 4. Confidentiality Each party keeps the other's commercial information
  + confidential for three years after the agreement ends ...
decision: denied with feedback

  status in_progress        99%
  status awaiting_approval  99%
[second round, revised placement, approved]

final status: completed
approved 7, denied 1
sections added: ['4. Confidentiality']
placement: clean
table: the out of hours charge reads 360, so that change applied
```

Two rounds, one denial, correct placement. The exact bug part one shipped into
the document never got in.

Now the part I got wrong, because it is the more useful half.

My first version of `--revise` denied the first change of *every* round, on the
theory that it would keep improving. It ran **twenty six rounds** and made
**fifty two decisions** before I stopped it. Every round is a billable turn.
Worse, the clause text degraded as it went: what started as my specified wording
with the three year term and the public domain carve out ended as generic
boilerplate about a "Receiving Party".

Two things to take from that:

**Nothing on the server caps the retries.** A denied change comes back
re-proposed, and it will keep coming back for as long as you keep denying it. The
stopping rule has to live in your code:

```python
if rounds > args.max_rounds:
    print("stopping: the server does not cap approval rounds, so this does")
    return 1
```

**Send feedback once, then decide.** Feedback is a correction, not a
conversation. If the second attempt is still wrong, the instruction is wrong, and
another round will not fix it.

## The other trap: changes are not independent

In the deny-all run above, look at what was on offer:

1. Insert the Confidentiality section
2. Change 320 to 360 in the table
3. Renumber "4. Service levels" to "5. Service levels"
4. Renumber "5. Governing law" to "6. Governing law"

Changes 3 and 4 only make sense if change 1 is approved. Approve the renumbering
while denying the insertion and you get a document that jumps from section 3 to
section 5, with nothing where 4 should be. The API will let you do that, and it
is right to: it cannot know your intent.

So a real gate judges a round as a set, not as a list of independent yes or no
questions. In a legal or compliance workflow, that grouping is the thing your
reviewer actually needs, and it is your job, not the API's.

## Keep the record

Every decision goes to `out/review-audit.json`:

```json
{
  "at": "2026-08-18T18:52:31+00:00",
  "job_id": "8551d5ee-fb33-4ffc-b8c8-e74abeb8945c",
  "chunk_id": "4b506d83-e008-406c-a67c-b12439e5a154",
  "approved": false,
  "feedback": "This landed inside section 3 ...",
  "old_text": "... out of hours Per visit 320 ...",
  "new_text": "... out of hours Per visit 360 ..."
}
```

If you needed an approval gate at all, you needed the log of who allowed what.
Build it on day one; it is fifteen lines and it is the artifact an auditor asks
for.

## Run it

```bash
python3 part2_review/review_gate.py               # you decide, interactively
python3 part2_review/review_gate.py --deny-all    # prove denial is real
python3 part2_review/review_gate.py --revise      # deny once with feedback
python3 part2_review/review_gate.py --approve-all # scripted, no prompts
```

Source: [`part2_review/review_gate.py`](../part2_review/review_gate.py).

## What part three adds

Everything so far is a two page contract that fits in a request body. Real
documents are fifty page tender responses with compliance tables, and at that
size the upload path changes, the response has to stop carrying the whole
document, and export can outlast an HTTP request.

[Part three](part-3-files-and-export.md) handles all three, and handles the
failures that come with them.

---

*Written by Rushikesh Vaidya as part of the SuperDocs Round 2 task.*
