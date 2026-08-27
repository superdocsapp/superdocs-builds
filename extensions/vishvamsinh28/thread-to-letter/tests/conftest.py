"""Fixtures. The stand-in runs as a real process on a real port."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tests" / "fake" / "server.py"
FAKE_KEY = "sk_fake_00000000000000000000000000000000"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class FakeServer:
    base_url: str
    process: subprocess.Popen


@pytest.fixture(scope="session")
def fake_server():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(FAKE)],
        env={**os.environ, "FAKE_PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"stand-in died: {proc.stderr.read().decode()[:1500]}")
        try:
            httpx.get(f"{base_url}/v1/sessions", timeout=1).raise_for_status()
            break
        except (httpx.HTTPError, OSError):
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("stand-in never became ready")
    yield FakeServer(base_url=base_url, process=proc)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def thread():
    from thread_to_letter.thread import load

    return load(ROOT / "threads" / "migration-project.mbox")


@pytest.fixture
def client(fake_server: FakeServer):
    from thread_to_letter.client import Client

    with Client(FAKE_KEY, fake_server.base_url) as c:
        yield c
