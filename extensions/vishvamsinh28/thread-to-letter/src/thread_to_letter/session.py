"""Naming the SuperDocs session a run works in.

A session id derived only from the thread looked tidy and was wrong: every run of the
same thread reused the same conversation, so turns accumulated. After two dozen of them a
live run came back with commitments about people who were not in the thread at all — the
model was answering from a session stuffed with the history of every previous attempt.

Every quote in that run failed verification and nothing reached the letter, which is the
safety net working. But the safety net should not be load-bearing for something this
avoidable.

So each run gets its own session. The thread hash stays in the name because it makes a
session recognisable when you go looking in the web app; the nonce is what makes it new.
"""

from __future__ import annotations

import hashlib
import os
import time

PREFIX = "thread2letter"


def new_session(thread_normalised: str) -> str:
    """A fresh session for one run of one thread."""
    digest = hashlib.sha256(thread_normalised.encode()).hexdigest()[:12]
    nonce = f"{int(time.time())%100000:05d}{os.urandom(2).hex()}"
    return f"{PREFIX}-{digest}-{nonce}"
