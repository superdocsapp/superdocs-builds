# Running it in a pipeline

The card this was built for asks for "a package plus an optional check that can
run in a build pipeline". This is that check.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | nothing at or above the failure threshold |
| `1` | the round trip lost identity |
| `2` | the check could not run: bad arguments, unreadable file, unusable capture |

`2` matters as much as `1`. A check that cannot run must never look like a check
that passed, so a missing file, an unparseable baseline and a capture with no
`document_sync` in it all exit `2` and say why on stderr.

By default `--fail-on error`, so:

- a stripped identifier, a duplicate, a regenerated document → exit `1`;
- a reorder, an omitted header/footer, new blocks the user typed → exit `0`.

Move the threshold with `--fail-on warning|info|never`. `--fail-on info` makes a
reorder fail the build, which some teams want on a document pipeline where
nothing is supposed to move.

## Output formats

```bash
chunk-guard check before.html after.html                       # human, colour when a TTY
chunk-guard check before.html after.html --format json         # machine, stable schema
chunk-guard check before.html after.html --format github \
                                          --file before.html   # workflow annotations
```

`--format github` emits `::error file=…,line=…,col=…,title=RULE::message`, so the
finding lands on the line of the captured HTML in the pull request rather than in
a log somebody has to open.

The JSON report carries no timestamps and no absolute paths, and its ordering is
deterministic, so two runs of the same inputs produce byte-identical output. That
is what makes it diffable and storable.

## GitHub Actions

A complete workflow is in [`examples/github-actions.yml`](../examples/github-actions.yml).
The short version:

```yaml
- run: npx chunk-guard check fixtures/round-trip/before.html \
                             fixtures/round-trip/after.html \
                             --format github --file fixtures/round-trip/before.html
```

## Pre-commit

```bash
#!/bin/sh
# .git/hooks/pre-commit
for pair in fixtures/*/; do
  npx chunk-guard check "${pair}before.html" "${pair}after.html" --quiet || exit 1
done
```

`--quiet` prints nothing when the check passes, so a clean commit stays silent
and a failing one prints the whole report.

## Baselines

The first run of this check against an integration that has been shipping for a
year finds real problems that cannot all be fixed today. Without a way to accept
the known ones, the check gets switched off — and a check that is switched off
finds nothing.

```bash
# Record what is already known
chunk-guard check before.html after.html \
  --baseline .chunkguard-baseline.json --update-baseline

# From now on, fail only on what is new
chunk-guard check before.html after.html --baseline .chunkguard-baseline.json
```

The baseline file lists findings by a stable key, plus the rule, the identifier,
the structural path and the text — so a reviewer reading the diff can see what is
being accepted, not just a hash. Findings it matches are moved into
`report.baselined` rather than deleted: a baseline hides a failure from the exit
code, never from the report.

Entries are matched on the rule, the identifier, the block's structural path and
its text. Change any of those and the entry stops matching, the finding comes
back, and `report.baselineApplied.stale` counts the entries that no longer match
anything.

Commit the baseline. Regenerate it deliberately, and read the diff.

## Checking a corpus

The CLI takes one pair at a time, on purpose: a check that loops over a directory
has to decide what to do about partial failure, and a shell loop makes that
decision visible.

```bash
status=0
for pair in fixtures/*/; do
  chunk-guard check "${pair}before.html" "${pair}after.html" \
    --format github --file "${pair}before.html" || status=1
done
exit $status
```

For anything more elaborate, use the library — `checkRoundTrip` is a pure
function over two strings, so a corpus run is a `map`.

## What to check in CI

Committed fixture pairs, not live captures. The point of a pipeline check is that
it fails when *your code* changes, and a live capture makes the result depend on
a session, an account and a network. Capture a pair once ([CAPTURE.md](CAPTURE.md)),
commit it, and let CI compare your editor's behaviour against it forever.

The stronger version of the same idea is the assertion in your editor's own test
suite — see [`examples/editor-roundtrip.test.js`](../examples/editor-roundtrip.test.js).
It runs against every block type your product supports and needs no fixtures at
all.
