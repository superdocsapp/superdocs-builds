#!/usr/bin/env bash
# The whole claim, in one command.
#
# Runs the migration twice against a deterministic local stand-in for the SuperDocs API:
# once straight through, once with the process SIGKILLed in the middle and resumed. Then
# diffs the two results. No API key, no network, no cost.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
WORK="$(mktemp -d)"
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }
good() { printf '\033[32m%s\033[0m\n' "$*"; }
bad()  { printf '\033[31m%s\033[0m\n' "$*"; }
rule() { printf '\033[2m%s\033[0m\n' "────────────────────────────────────────────────────────────"; }

cleanup() {
  [[ -n "${FAKE_PID:-}" ]] && kill "$FAKE_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

export FAKE_STATE_DIR="$WORK/fake"
export FAKE_PORT="$PORT"
uv run python tests/fake/server.py >"$WORK/fake.log" 2>&1 &
FAKE_PID=$!

for _ in $(seq 1 50); do
  curl -sf "http://127.0.0.1:$PORT/v1/sessions" >/dev/null 2>&1 && break
  sleep 0.2
done

export SUPERDOCS_API_KEY="sk_demo_00000000000000000000000000000000"
export SUPERDOCS_BASE_URL="http://127.0.0.1:$PORT"
export LONGHAUL_STATE_DIR="$WORK/state"
SPEC="jobs/runbook-migration.yaml"

rule
bold "1. The control run: six runbooks, twenty steps, no interruption."
dim   "   A synthetic engineering-runbook migration. Nothing real, nothing confidential."
rule
uv run longhaul run --spec "$SPEC" --run-id democontrol0
uv run longhaul export --run democontrol0 --format markdown --out "$WORK/out" >/dev/null
CONTROL="$(cat "$WORK"/out/democontrol0/*.md | shasum -a 256 | cut -d' ' -f1)"
echo
dim "   sha256 of the exported documents: $CONTROL"

rule
bold "2. The same job again — killed with SIGKILL partway through."
rule
rm -f "$FAKE_STATE_DIR"/state.json
rm -rf "$LONGHAUL_STATE_DIR"

LONGHAUL_TRACE="$WORK/trace.txt" uv run longhaul run --spec "$SPEC" --run-id demotrace000 >/dev/null 2>&1
TOTAL="$(wc -l <"$WORK/trace.txt" | tr -d ' ')"
KILL_AT="$(sed -n "$((TOTAL / 2))p" "$WORK/trace.txt")"

rm -f "$FAKE_STATE_DIR"/state.json
rm -rf "$LONGHAUL_STATE_DIR"

dim "   killing at checkpoint: $KILL_AT"
set +e
LONGHAUL_KILL_AT="$KILL_AT" uv run longhaul run --spec "$SPEC" --run-id demokilled00 >"$WORK/killed.log" 2>&1
CODE=$?
set -e
if [[ $CODE -eq 137 ]]; then
  good "   process killed by signal 9. No unwinding, no cleanup, no handover."
else
  bad  "   expected exit 137 (SIGKILL), got $CODE"; exit 1
fi

echo
dim "   what the ledger knows, with the process gone:"
uv run longhaul status --run demokilled00 2>&1 | tail -4

rule
bold "3. Resume. A new process, given nothing but a database path."
rule
uv run longhaul run --spec "$SPEC" --run-id demokilled00
uv run longhaul export --run demokilled00 --format markdown --out "$WORK/out" >/dev/null
RESUMED="$(cat "$WORK"/out/demokilled00/*.md | shasum -a 256 | cut -d' ' -f1)"
echo
dim "   sha256 of the exported documents: $RESUMED"

rule
if [[ "$CONTROL" == "$RESUMED" ]]; then
  good "The interrupted run and the uninterrupted run are byte-identical."
else
  bad  "MISMATCH — the interrupted run produced different bytes."
  diff -ru "$WORK/out/democontrol0" "$WORK/out/demokilled00" || true
  exit 1
fi

DUPES="$(curl -s "http://127.0.0.1:$PORT/_test/stats" |
  python3 -c 'import json,sys; print(len(json.load(sys.stdin)["duplicate_turns"]))')"
if [[ "$DUPES" == "0" ]]; then
  good "The server received no edit instruction twice."
else
  bad  "$DUPES instructions were sent more than once."; exit 1
fi
rule
dim "That is one kill point. 'make proof' does the same at every checkpoint a run"
dim "reaches — all $TOTAL of them for this job — and diffs every one."
