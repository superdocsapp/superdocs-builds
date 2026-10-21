# Progress log -- Multi-Agent Editorial Review Loop

## Before any API calls: validated `verify_issues()` against known ground truth

Same discipline as the other two builds. Hand-built a bloated,
pre-review draft (94-word Executive Summary, stale TAM/market-share
figures, one passive-voice sentence) and a fully-fixed version, ran
`verify_issues()` against both with zero API cost: the broken draft
correctly failed all four real checks (and correctly passed the
already-fine "risk mitigations untouched" control), the fixed version
correctly passed all five.

## Run 1: the concurrency test found something more interesting than planned

The original design fired the fact-check and style-review turns as
genuinely concurrent HTTP requests (`ThreadPoolExecutor`, not a
sequential loop) against two disjoint sets of sections, to empirically
test whether two simultaneous edits to one session could collide.

They didn't get the chance to collide: **`POST /v1/chat/async` returned
`409 Conflict` outright** the instant the second submission landed while
the first chat job was still active on that session. This is a stronger
answer than the empirical test was designed to produce -- collisions
aren't just absent, they're structurally prevented, because the platform
won't accept two simultaneous chat jobs against the same session in the
first place.

Fixed by adding retry-with-backoff on 409 to `run_turn` (`MAX_409_RETRIES
= 40`, 5s interval) -- treating the rejection as "wait your turn" instead
of a hard failure, which is what a real caller has to do against this API
if it wants two logically-independent agents both editing one document.

## Run 2: a script crash, and a false failure underneath it

Re-ran with the 409 retry in place. Round 1 completed (style-review hit
7 real 409s waiting out fact-check's job, then ran and completed
normally). Verification reported `risk_mitigations_untouched: count 1`
(expected 2) -- looked like a real content problem, so the loop correctly
continued to round 2 per its own termination logic. Round 2's style-review
turn then exceeded the client's 400-second wait and the script crashed
with an unhandled `TimeoutError`, before writing any output file.

Diagnosed by querying the session directly (`GET /v1/sessions/{id}/documents`,
authoritative, unaffected by the local crash) rather than re-running
blind. The real document state showed round 1 had actually fully
succeeded: both risks' mitigations were genuinely present in the text --
one said `"Mitigation: ..."` (noun), the other said `"To mitigate the
risks..."` (verb). `verify_issues()`'s regex, `[Mm]itigation`, only
matched the noun form. Fixed to `[Mm]itigat` (the stem, catching
"mitigate," "mitigation," "mitigating," all forms). Re-checked against
the actual round-1 document with the fixed regex, no API cost: all five
checks passed. The crash-triggering round 2 had been chasing a problem
that didn't exist.

(`GET /v1/sessions/{id}/jobs` came back with zero jobs for this session
despite real chat activity, which is odd and possibly worth a closer look
some other time -- not investigated further here since the document-state
endpoint gave a complete, authoritative answer on its own.)

## Run 3: a clean run, and a real, different failure

Re-ran once more, cleanly, with the regex fix in place -- no crash this
time. Round 1: `risk_mitigations_untouched: count 1` again, same as
before the crash's "fix." This time it's real, not a verification bug:

The second risk's mitigation was reworded from the original
`"Mitigation: qualify a second supplier"` to `"To address this
vulnerability, we intend to qualify a second supplier"` -- no form of
"mitigate" anywhere in it. The mitigating *action* is still there (the
sentence still says what will be done about the risk); the specific word
the style guardrail's language leans on is not. This happened even
though `FACT_CHECK_INSTRUCTION` -- the only turn scoped to touch Risk
Assessment at all -- explicitly says "do not change anything else in the
document... no other sentence in Market Analysis or Risk Assessment
beyond the one figure in each." The fact-check turn rewrote both risk
items into fuller prose while correcting the one figure, not just the
figure in place.

Deliberately did not patch the regex a second time to also match
"address." The first fix (noun form to stem, same underlying word) was a
correction of a real bug in the check. Chasing this one the same way
would mean adding every synonym a model might reach for until the check
stops meaning anything -- at that point it's not verifying the guardrail
anymore, it's verifying "did the reviewer output some sentence." This is
a real, different finding, not the same bug twice: **`FACT_CHECK_INSTRUCTION`'s
explicit "don't change anything else" scope wasn't fully honored -- the
substance of the edit stayed correct, but the turn reworded surrounding
content it was told to leave alone, and that reword happened to drift
away from the literal word a downstream guardrail cares about.** Round 2
re-ran identically (fact-check and style-review both had nothing new to
find, since the only remaining issue isn't something either instruction
is scoped to fix) and the loop correctly hit its hard cap and stopped --
the termination guarantee held exactly as designed, independent of
whether the document ever converged.

## Final result

**Overall: FAIL, 4 of 5 checks** (`tam_corrected`,
`competitor_share_corrected`, `exec_summary_length`,
`passive_voice_fixed`: PASS; `risk_mitigations_untouched`: FAIL, for the
real reason above). 2 of 2 rounds run, hard cap reached, loop terminated
as designed. `output/reviewed_launch_brief.docx`,
`output/final_document.html`, `output/verification_result.json`, and
`output/round_log.json` all reflect this run.

Both things this build set out to prove came back with real answers, not
the ones originally hypothesized:

- **No section collisions**: true, but not because two concurrent edits
  landed side by side without conflict -- true because the platform
  rejects the second concurrent submission outright with 409 Conflict.
  Structurally prevented, not just empirically absent.
- **Provable loop termination**: true, and cleanly demonstrated -- the
  loop ran its full `MAX_ROUNDS = 2` and stopped on the hard cap when
  convergence didn't happen, exactly as the bounded `for` loop guarantees
  it would.
