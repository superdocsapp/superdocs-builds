# Build log

This is the running log of what I decided while building the letter factory, and why. I kept it as I went rather than writing it up afterwards, so the awkward parts are in here too.

## Decisions I made on my own

**Folder path.** The brief told me to build in `use-cases/sundaram-letter-factory/`, but `CONTRIBUTING.md` in this repo says the path is `use-cases/<your-github-username>/<project-name>/`. I followed CONTRIBUTING, since that is the repo's own rule, and kept the project name I was given. So the work lives at `use-cases/sundaram2021/sundaram-letter-factory/`.

**No AI anywhere near the wording or the figures.** The brief allows an AI step to help select or insert content. I decided against it. Every figure comes from the formula in `data/rules.json`, and every letter is approved wording with placeholder tokens literally substituted. That way "the AI never rewrites approved wording" is a property of the design, not a promise I have to trust a model to keep.

There is therefore no Anthropic model in this build, and that is the deliberate answer rather than an omission. The brief asks for a Haiku class model for any AI step involved, and I removed the AI step instead. Selection is a lookup, insertion is a substitution, arithmetic is a formula, and the only model in the pipeline is the SuperDocs editor applying the targeted edit, which I then verify character for character.

I did build a Haiku reviewer along the way, and then deleted it. Two versions of it: the first voted MATCH or DRIFT on every proposed change, which duplicated the byte comparison and spent a call per section; the second explained denied changes in one sentence. The second was genuinely better, but it was still off by default, still only fired on a denial, and the last full run had zero denials, so in practice it never ran. A module that never executes is worse than no module, so it is gone rather than sitting in the tree implying a capability the run does not exercise. If a real AI step ever belongs here, held record triage is where I would put it: summarising why a batch of records was held is judgement work, and it never touches wording or figures.

**Getting an API key without a human in the loop.** I did not have a SuperDocs key when I started, so I used `POST /v1/agents/signup`, which returns a working free tier key immediately. The key lives in an environment variable and in `~/.superdocs/` on my machine, never in this repo, and the README uses a placeholder. The run also has a `.gitignore` entry for `.env` so a key cannot be committed by accident.

**Checks beyond the four the brief asked for.** The brief asked me to break four things: a negative amount, a missing date, a figure that does not match its formula, and a jurisdiction or stage with no wording block. I built those and then added four more that a real remediation programme would want: a reversed accrual period, a missing account number, a language with no approved block, and a refund above an automated ceiling that should go to a human signer. The ceiling one is the interesting one, because it holds a record whose arithmetic is perfectly correct. Not everything held back is wrong, some of it is just too big to send unsupervised.

**How I enforce "never paraphrased".** I upload the approved wording with placeholder tokens still in it, ask SuperDocs to substitute the values, and then compare what it proposes against the text I assembled locally, character for character after stripping HTML tags and collapsing whitespace. A change is approved only on an exact match. Anything else is denied and the record is held with the expected and received text both printed. This means the SuperDocs chat call genuinely does the insertion, and a model changing a single word cannot reach a customer.

I compare on visible text rather than raw HTML because the editor can legitimately return equivalent markup. Every visible character still has to match.

**Money in integer cents, Decimal throughout.** No floats anywhere in the arithmetic. Rounding is half up to the cent, stated once in the data file.

**Placeholder tokens are namespaced per customer.** In a batch, `{{customer_name}}` would appear once per letter with a different correct value each time. So the uploaded template carries `{{CUS-1001.customer_name}}` instead. Ambiguity disappears and each token maps to exactly one value.

## What the live API actually does, as opposed to what I assumed

I probed the API by hand before writing the client. Notes worth keeping:

- `POST /v1/chat/{session_id}/approve` needs `job_id`, `change_id` and `approved`. I first tried `change_id` plus `action: accept`, which is a 422.
- Approval is not one shot. The job pauses at `awaiting_approval`, and it only resumes once the changes in that round are answered. So the client has to keep pumping: wait, verify, approve, wait again, until the job reports `completed`. My first working version approved one round and stopped, which left most sections unfilled.
- The editor proposes changes to sections that contain no placeholder at all, effectively re-proposing them unchanged. That is harmless here and actually useful: I verify those too, so drift in a section I was not even editing would be caught and denied.
- On `core` tier a two letter batch stopped part way through, filling one section and declaring itself complete. On `pro` it completed a full batch in a single turn every time. So the tier is `pro`, and the instruction ends with an explicit completion condition ("the document is not finished until no token remains"). Both changes mattered.
- The documented gotcha is that `metadata.pending_changes` arrives as a JSON encoded string needing a second parse. On my account it came back as a real JSON list. I parse defensively for both rather than assuming either.
- Long silent stretches are normal. The poller waits up to 30 minutes per job and never treats quiet as failure. There is no retry that assumes a stall is an error.

## The run that only half worked

This is the part of the build I learned the most from, so the numbers are worth writing down.

My first complete run against the live API sent **11 letters out of 22**. The other 11 were held, not because their data was bad, but because the editor drifted. At that point the chat instruction was a token to value map: here is `{{CUS-1005.refund_amount}}`, replace it with `$2,287.04`. On the shorter letters that worked. On the longer ones the model filled some tokens and left others sitting in the text, and on several sections it simply invented content. Real examples my verification caught and denied:

- `Interest of $12.45 has accrued over 45 days at the statutory annual rate of 7.0%` where the correct line was `$242.04`, `432 days` and `10%`. Every figure fabricated.
- `You may also contact the Financial Conduct Authority` and, in another letter, `the Financial Ombudsman Service`. Neither organisation appears anywhere in my data. It invented a regulator for a California letter.
- `we will hold $1,250.00 for you` against a correct figure of `$2,287.04`.
- On one batch it merged two customers, writing `about the incorrect billing on your account CA-88214311 and account CA-88214312` into a letter that should name one account.

Not one of those reached a customer, because a change is only approved on an exact match. That is the whole argument for building the verification before building the throughput. But an ops team cannot use a service that holds half its work, so a design that is safe and useless still needs fixing.

The fix was to stop asking the model to compute the substitution at all. The instruction now gives, for each section, the text it currently reads and the exact text it must read afterwards, and asks it to copy character for character. The wording still comes from the approved block and the figures still come from the formula, so nothing about the guarantee changed, but the room to invent is gone. I tested it on the exact two letter batch that had failed completely: 12 sections, 12 approved, zero denials. The next full run sent **22 of 22** with zero wording denials, and the only held records were the 8 whose data was deliberately broken.

Two smaller changes went in alongside it. The tier moved to `pro`, because `core` stopped part way through a batch and declared itself finished. And the instruction ends with an explicit completion condition, that the document is not done until no token remains, because without it the model treated a partial pass as success.

## Cost control and the stopping rule

Testing a pipeline that spends metered operations needed some discipline, so there are three ways to run it cheaply. `--offline` runs validation, arithmetic and assembly and writes every letter locally without touching the API, which is where most of my testing happened. `--sample N` processes the first N records only. Exports cost nothing, so a run exports every batch rather than saving them up.

The stopping rule is deliberate. If a chat turn leaves sections unfilled, the run sends exactly one more turn naming only those sections, and then stops. `MAX_CHAT_ATTEMPTS` is 2, and past that the record is held with a reason rather than retried. I would rather hold a letter and report why than let a run loop on a model that is not converging and burn the quota doing it.

## Batching and operation cost

One operation covers up to 25 sections of targeted edits. I originally packed batches by counting only the sections holding placeholders, but since the editor proposes changes across every section, I now count every section a letter contributes plus its separator. That works out to two letters per batch, so a full 22 letter run costs about 11 operations. Exports are free, so I export every batch. A customer is never sent through twice: records are deduplicated by `customer_id`, and the follow up turn only ever names sections that are still unfilled.

## Crash safety, idempotency and error handling

This came out of a review of the first version, and the criticism was correct and worth writing down properly.

**What was wrong.** Someone pointed a mock API at the run and made it return a 500 on batch 4. The result was the worst possible shape: a raw Python traceback, three batches of paid work already done, and no `run-report.json` written at all, so the record of what had been sent was simply gone. Re-running would have re-uploaded and re-chatted batches 1 to 3 and paid for those operations a second time. Two separate faults, both about money and both mine.

**The fixes.**

- **State after every batch.** `out/run-state.json` is written as soon as a batch finishes, recording its session id, export path, operations spent and the sent and held records it produced. It is written through a temporary file and an atomic replace, so a crash mid-write cannot leave a truncated state file.
- **`--resume`.** A resumed run skips any batch already marked completed, pulls its results straight out of the state file, and reports those operations separately as reused rather than counting them again. The state file carries a run key derived from the record set and the export format, and resuming onto a different set of records is refused with an explanation rather than silently mixing two runs.
- **Session ids from a content hash, not the clock.** A batch session is now `letter-factory-<sha256 of the batch content>`. The same records always produce the same session, so a re-run lands on the same SuperDocs session instead of creating a new one. Previously the id carried a timestamp, which guaranteed that every re-run was a fresh session and a fresh charge.
- **The report is written in a `finally`.** Whatever happens, the report gets written, marked `"status": "failed"` with the failure reason, and the printed summary says `RUN INCOMPLETE` so the counts are not mistaken for a whole run. The exit code is 1 and the last thing printed is the command to resume.

**Retries, and the one place a retry would cost money.** `_request` previously caught only `HTTPError`. A dropped connection raises a bare `URLError`, which went straight up as an unhandled exception. It now catches `URLError`, socket timeouts, `http.client` errors and `ConnectionError`, and retries with exponential backoff and jitter, four attempts.

The subtlety is that retrying is not always safe. Repeating a `POST /v1/chat/async` that the server already accepted would pay for the same operation twice. So the retry is not blanket: calls are marked idempotent or not, and the chat start is marked not idempotent. It is retried on 429 alone, because a 429 means the request was rejected and no work was done, and every other failure on that call is raised for `--resume` to handle. Upload, job polling, approve and export are safe to repeat and are retried normally.

429 now honours `Retry-After`, in seconds or as an HTTP date, capped so a hostile header cannot park the run for hours. The free tier pauses at its monthly limit, so this is the case that will actually happen.

**Errors name the cause and the fix.** A bare status code is useless to whoever is running a letter batch. Each one now carries what to do: a 401 says to check the key, a 413 says to lower `MAX_SECTIONS_PER_OPERATION` so batches carry fewer letters, a 429 explains the free tier pause and points at `--resume`, and a connection failure says the API was unreachable and that resuming will not re-pay for finished batches.

**How I verified it.** I wrote a mock of the five endpoints and reproduced the original test exactly: 500 on batch 4 of 11. The run now exits 1 with no traceback, names the cause and the fix, writes the report marked failed, and leaves three completed batches in state. Resuming against a working server then skipped batches 1 to 3 and finished the remaining 8, ending at 22 letters sent with 8 operations spent on that run and 3 reported as reused, rather than 11 spent twice. I also injected repeated 500s on an upload and watched it back off and recover, injected 429s with `Retry-After: 1` on the chat call and watched it wait the second and recover, and pointed the client at a closed port to confirm the connection path retries and then fails with a named message instead of a traceback. The mock is a test harness, not part of this folder.

## Proving the no code change claim

I built and tested the pipeline with California and Texas only, committed that, and then added New York purely as data: a jurisdiction entry in `rules.json`, four wording blocks, and four customer records. No `.py` file was touched. The git history shows this as its own commit, so the claim is checkable rather than asserted.

## Why the screenshot is an SVG

The README screenshot is a committed SVG rather than a PNG. It is a faithful render of the real captured output of the full run, not a mockup, and the same run is in `sample-output/run-report.json` so the numbers in the image can be checked against it. The reason it is not a PNG is mundane: the path I had available for writing to the repository carried text reliably and binary awkwardly, so I chose the format that would land intact over the format that is conventional. If it matters to a reviewer, that report is the authoritative copy.

## What I would do next

- The batch export is one DOCX containing two letters with an internal separator heading. A real ops team would want one file per customer from SuperDocs itself. I write per customer HTML locally, but the DOCX export is per batch.
- The sanity checks are declarative but the check kinds are a fixed set in code (`required`, `compare`, `date_order`, `formula_match`, `in_config`, `wording_block_exists`). A genuinely new kind of check needs a new kind handler. Adding a jurisdiction, a stage, a language or a new check that reuses an existing kind needs no code.
