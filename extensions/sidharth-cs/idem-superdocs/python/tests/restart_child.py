"""Claims an operation key, sends the request, and dies before recording the
outcome. Run as a subprocess by test_faults.py.

os._exit skips every cleanup path there is: no finally blocks, no atexit, no
flushing. It is the closest thing to pulling the power cord that a test can do,
and it is the only honest way to prove the record survives (N4).
"""

import os
import sys

from idem import Idempotent, Policy
from tests.fakeserver import FakeServer

store_path, server_path, key, policy_path = sys.argv[1:5]

idem = Idempotent(store_path, Policy.load(policy_path), sleep=lambda _s: None)
server = FakeServer(server_path)


def operation():
    result = server.chat_async(key)
    # The edit is applied and the server answered. This process now dies
    # holding that answer, exactly as a crash between the response and the
    # commit would.
    os._exit(9)


idem.run(key, operation)
