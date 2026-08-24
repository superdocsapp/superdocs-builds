#!/usr/bin/env python3
"""ACCORD Mac capture-helper.

Connects OUTBOUND over secure WebSocket to the Railway backend and waits for
START/STOP commands from the Zoom panel. On START it spawns the existing
Swift audio-fetcher (ScreenCaptureKit + mic → 4s PCM chunks → POST /audio →
Groq) so real transcript events flow into the meeting session. On STOP it
SIGTERMs the capture process, which flushes its partial chunk and drains
in-flight uploads before exiting.

Command protocol (backend → helper → backend):
  backend → helper : {"cmd":"start","meeting_uuid":"<uuid>"}
  helper  → backend: {"cmd":"started","meeting_uuid":"<uuid>"}   (only on successful spawn)
  backend → helper : {"cmd":"stop"}
  helper  → backend: {"cmd":"stopped","meeting_uuid":"<uuid>"}
  backend → helper : {"cmd":"ping"}
  helper  → backend: {"cmd":"pong"}

Usage:
  HELPER_AUTH_TOKEN=<token> HELPER_WSS_URL=wss://... python3 helper.py
  or:  python3 helper.py --url wss://... --token <token>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import ssl
import subprocess
import sys

import websockets

DEFAULT_URL = "wss://live-deliverable-zoom-app-production.up.railway.app/api/ws/helper"
RECONNECT_DELAY_S = 3.0
# The Swift capture runs "until signal" — a very large ceiling with a
# SIGTERM-driven exit (the audio-fetcher's StopFlag loop).
RUN_FOREVER_SECONDS = "86400"


def log(msg: str) -> None:
    print(f"[helper] {msg}", flush=True)


def _swift_binary() -> str:
    env = os.environ.get("HELPER_SWIFT_BINARY")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audio-fetcher", "build", "audiofetcher")


def derive_backend(wss_url: str) -> str:
    """wss://host/api/ws/helper -> https://host  (the /audio origin)."""
    scheme, _, rest = wss_url.partition("://")
    host = rest.split("/", 1)[0]
    return ("https" if scheme == "wss" else "http") + "://" + host


class CaptureRunner:
    """Owns the Swift audio-fetcher subprocess lifecycle (START spawn, STOP
    SIGTERM). Reuses the existing binary verbatim — no capture rewrite."""

    def __init__(self, backend: str, use_mic: bool = True) -> None:
        self.backend = backend
        # The mic is opt-in at the Swift level; this helper had it hard-wired
        # on. ScreenCaptureKit alone captures what the MEETING is saying —
        # which is the actual job — so --no-mic gives a clean capture in a
        # noisy room, and lets the call's audio be the only input.
        self.use_mic = use_mic
        self.binary = _swift_binary()
        self.proc: subprocess.Popen | None = None
        self.uuid: str | None = None

    @property
    def capturing(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, meeting_uuid: str) -> bool:
        if self.capturing:
            # Duplicate START while already capturing — ignore, re-ACK.
            log(f"START ignored — already capturing meeting_uuid={self.uuid}")
            return True
        self.uuid = meeting_uuid
        log(f"START received meeting_uuid={meeting_uuid} → spawning {self.binary}")
        try:
            self.proc = subprocess.Popen(
                [
                    self.binary,
                    "--uuid", meeting_uuid,
                    "--backend", self.backend,
                    *(["--mic"] if self.use_mic else []),
                    "--seconds", RUN_FOREVER_SECONDS,
                ],
                stdout=None, stderr=None,  # inherit — logs appear in this terminal
            )
            log(f"capture process spawned pid={self.proc.pid}")
            return True
        except FileNotFoundError as exc:
            self.proc = None
            log(f"FAILED to spawn capture binary: {exc}")
            return False

    def stop(self) -> None:
        if self.capturing:
            log(f"STOP received → SIGTERM pid={self.proc.pid}")
            try:
                self.proc.send_signal(signal.SIGTERM)
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                log("capture did not stop in time — SIGKILL")
                self.proc.kill()
                self.proc.wait()
            log("capture stopped")
        else:
            log("STOP received — no capture running")
        self.proc = None

    def terminate(self) -> None:
        self.stop()


def _ssl_context(url: str):
    """A Homebrew or python.org Python on macOS ships no CA bundle of its own
    and cannot verify any TLS certificate until someone runs
    'Install Certificates.command'. Without this the helper cannot reach the
    backend at all: websockets falls back to the empty system trust store and
    every connect fails with CERTIFICATE_VERIFY_FAILED, retrying forever.
    certifi carries a bundle and is already installed (httpx depends on it).
    Verification is never disabled — this is the operator's own machine
    talking to their own backend over the public internet."""
    if not url.startswith("wss://"):
        return None
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        log("certifi not installed — falling back to the system trust store; "
            "if this fails with CERTIFICATE_VERIFY_FAILED, run: pip install certifi")
        return ssl.create_default_context()


async def run(url: str, token: str, runner: CaptureRunner) -> None:
    uri = f"{url}?token={token}"
    ctx = _ssl_context(url)
    current_uuid: str | None = None
    while True:
        try:
            async with websockets.connect(uri, ssl=ctx) as ws:
                await ws.send(json.dumps({"cmd": "hello"}))
                log(f"connected: {url} — waiting for commands")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except (ValueError, TypeError):
                        log(f"ignoring non-JSON: {raw[:80]!r}")
                        continue
                    cmd = msg.get("cmd")
                    if cmd == "start":
                        current_uuid = msg.get("meeting_uuid", "")
                        if runner.start(current_uuid):
                            await ws.send(json.dumps({"cmd": "started", "meeting_uuid": current_uuid}))
                    elif cmd == "stop":
                        log("STOP received")
                        runner.stop()
                        # Echo the meeting_uuid so the backend can match the
                        # ACK back to the session (same as the started ACK).
                        await ws.send(json.dumps({"cmd": "stopped", "meeting_uuid": current_uuid}))
                    elif cmd == "ping":
                        log("PING received")
                        await ws.send(json.dumps({"cmd": "pong"}))
                    else:
                        log(f"ignoring unknown cmd: {cmd!r}")
        except websockets.exceptions.ConnectionClosed as exc:
            log(f"connection closed ({exc.code}) — reconnecting in {RECONNECT_DELAY_S}s")
        except OSError as exc:
            log(f"connect failed: {exc} — reconnecting in {RECONNECT_DELAY_S}s")
        await asyncio.sleep(RECONNECT_DELAY_S)


def main() -> int:
    ap = argparse.ArgumentParser(description="ACCORD Mac capture-helper")
    ap.add_argument("--url", default=os.environ.get("HELPER_WSS_URL", DEFAULT_URL))
    ap.add_argument("--token", default=os.environ.get("HELPER_AUTH_TOKEN", ""))
    ap.add_argument(
        "--no-mic", action="store_true",
        default=os.environ.get("HELPER_NO_MIC", "") not in ("", "0", "false"),
        help="capture only the meeting's audio, not this machine's microphone",
    )
    args = ap.parse_args()
    if not args.token:
        print("error: HELPER_AUTH_TOKEN not set (use --token or the env var)", file=sys.stderr)
        return 2

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = CaptureRunner(derive_backend(args.url), use_mic=not args.no_mic)
    log(f"capture source: {'Zoom audio + microphone' if not args.no_mic else 'Zoom audio only (mic off)'}")

    def on_exit_signal():
        # Stop any running capture before the helper itself exits.
        runner.terminate()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_exit_signal)
    try:
        loop.run_until_complete(run(args.url, args.token, runner))
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
    log("exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
