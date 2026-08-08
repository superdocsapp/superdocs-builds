# Payer appeals — drafted, reviewed, exported

When a health insurer denies a claim, someone on the provider side writes an appeal letter that
pairs the payer's stated reason for denial with the specific clinical facts that rebut it.
Getting that pairing right by hand is slow. Getting it *wrong* by machine is worse.

This app takes **one denial reason and one clinical fact**, drafts an appeal letter on the
SuperDocs API, holds every proposed change for a human decision, and exports only what a person
approved.

Built by **Aayush Mishra** for the SuperDocs engineer task.

---

## Run it

```bash
cp .env.example .env          # add your SUPERDOCS_API_KEY
./run.sh                      # http://localhost:8080
```

That is the whole setup. Everything in the demo is fictional and the UI says so in a banner
that does not go away.

---

## The thing this app is actually about

A model given a denial reason and a clinical fact will write a fluent, professional appeal
letter **whether or not the fact answers the denial**. When they do not match, the way it
bridges the gap is by inventing clinical detail.

A fabricated clinical assertion in a payer appeal is not a bad user experience. It is a false
statement submitted to an insurer over a clinician's name.

So the app does three things a plain wrapper would not:

### 1. It checks relevance *before* drafting

`app/grounding.py` classifies the denial into a category — prior authorisation, medical
necessity, timely filing, coding, eligibility, duplicate — and asks whether the supplied fact
speaks to that category. The verdict is shown to the reviewer before they read a word of the
letter.

### 2. When the fact does not fit, it says so in the letter

It still drafts. Refusing would just push the user to write it by hand with no warning at all.
But it drafts honestly. Given a prior-authorisation denial and a fact about seasonal allergies,
the letter it produced was:

> "Please note that the documentation directly addressing the prior authorization requirement
> is **not enclosed** with this letter. We will forward it..."

It stated the fact accurately, admitted the gap, and asked for reconsideration once real
documentation is supplied. It did not manufacture a rebuttal.

### 3. It flags specifics nobody supplied

`unsupported_specifics()` finds numbers, dates, dosages and measurements that appear in the
drafted letter but in none of the inputs. It cannot judge meaning — but a payer will verify
every concrete detail, and a clinician will be asked to stand behind it, so the reviewer sees
those before sending.

---

## The human gate is real

- Every proposed change is shown with **before and after**, and decided individually.
- Rejecting one leaves the others untouched.
- **Export is refused with a 409 while any decision is outstanding.** A review you can skip is
  decoration.
- A large edit arrives in **several rounds**; the app tells the reviewer when more changes are
  waiting rather than letting them believe they have seen the whole letter.

In a live run: 4 changes proposed, 3 approved and 1 rejected. In the exported `.docx` the
rejected section still reads `[What is enclosed, and what is not.]` — the placeholder was never
filled, because that change was rejected. The rejection is visible in the artefact.

---

## What it uses

| SuperDocs surface | Used for |
| --- | --- |
| `POST /v1/chat/async` with `approval_mode: ask_every_time` | Draft into the letter template without self-applying |
| `GET /v1/jobs/{id}` | Poll until a human decision is required |
| `POST /v1/chat/{session}/approve` | Per-change approve/reject with feedback |
| `POST /v1/documents/export` | `.docx` / `.pdf` |
| `GET /v1/sessions/{id}/jobs` | Recover a session wedged by an abandoned review |

The letter starts from a **template document** rather than being generated from nothing. That
is deliberate: appeal letters have a house format a compliance team already approved, and
starting from a document means the model performs targeted edits on named sections — which is
what SuperDocs is good at — rather than generating prose, which everything is good at.

---

## Things I learned against the live API

Encoded here so the next person does not spend the same afternoon:

- The upload field is **`file_base64`**, not `content_base64`. The 422 body is the only place
  the correct name appears.
- `pending_changes` can be present with a **null** value, so `.get("pending_changes", [])`
  returns `None`, not `[]`. That crashed this app once.
- A large edit arrives in **several approval rounds**. Approve once and wait for completion and
  you poll forever.
- A job stuck in `awaiting_approval` **cannot be cancelled** — `cancel_job` returns
  `400 "Job cannot be cancelled"` — even though the 409's own `suggested_action` recommends
  exactly that. The way out is to **deny** its pending changes.

---

## Honest limitations

- **In-memory drafts.** A restart loses anything in flight. Fine for a demo, not for a clinic.
- **The relevance check is coarse.** It is keyword-and-category matching, not clinical
  judgement. It reliably catches the obviously-wrong pairing; it will not catch a fact that is
  topically right and substantively weak. It exists to make a reviewer look, not to decide.
- **`unsupported_specifics` is not a hallucination detector.** It finds concrete tokens absent
  from the inputs. A fabricated *qualitative* claim — "the patient's condition was severe" —
  passes it untouched.
- **One fact per appeal.** Real appeals cite several. The card specified one, and the pairing
  logic is what is being demonstrated.
- **No authentication, no multi-user.** Single-reviewer demo.
- **Not a medical device and not legal advice.** It drafts a letter a qualified human must read
  before it goes anywhere.

## License

MIT.
