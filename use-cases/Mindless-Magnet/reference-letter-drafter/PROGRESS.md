# Assumptions log

Ambiguities in the brief, the call I made, and why. Per the task doc: a logged assumption counts in
your favour.

**The card names "templates, memory, export" but the minimum contract is four calls.**
Built the four (upload, chat, approve, export) first and completely, then added templates and
cross-session memory on top. If the four are not solid the rest is decoration.

**"In the writer's own voice" is underspecified.**
Two mechanisms, neither of which claims more than it does: a prior letter uploaded as a SuperDocs
template, and a cross-session memory note keyed on the writer's email. Voice cloning from a single
sample is not a claim I can support, so the README does not make it.

**"Strength calibrated honestly" needed an operational definition.**
Chose a four-point ordinal band declared by the writer, not inferred from their prose. Inferring the
band from how warmly someone describes a colleague reproduces the exact bias the tool exists to
remove.

**Whether to auto-correct an inflated letter.**
Decided no. Findings surface; the human acts. A tool that silently rewrites someone's assessment of a
colleague has substituted its judgement for theirs, and the writer is the one signing it.

**Whether the verifier should be a required dependency.**
Decided no. It degrades honestly to deterministic-only with a stated reason, so the app runs on a
SuperDocs key alone. The eval harness does require it and exits with an explanation rather than
producing a meaningless number.

**Which model to use as the verifier.**
Originally left configurable against any OpenAI-compatible or Anthropic endpoint, as a separate call
outside SuperDocs. Reverted: the brief is to build on the SuperDocs API, and reaching past it to a second
vendor is a dependency the app does not need. The verifier is now a second, isolated SuperDocs chat call
(fresh session, no cross-session memory, told not to edit its scratch document) — same API, same key,
no separate config. Confirmed against the live API that a pure Q&A turn like this is not billed as an
operation.

**Whether to render proposed changes as HTML.**
Decided no, after initially doing so. Model-generated HTML derived from third-party text is an XSS
class I do not have to be in. Word-level text diff removes it entirely and reads better.

**Test strategy: what counts as a real test.**
Everything runs with no key and no SuperDocs calls. HTTP behaviour is tested against a real localhost
server rather than a stubbed `fetch`, because stubbing `fetch` proves the stub was called the way the
test expected, which is a tautology.

**Eval sample size.**
Defaults to one letter per fixture (8 total) with a 20-operation ceiling. Small on purpose: the brief
warns to learn the operation budget on day one, and a harness that can quietly drain a free tier is a
harness nobody runs twice.

**Fixture data.**
Every person, company and institution in `evals/fixtures/` is invented. No real reference material,
no real names, no third-party private files.
