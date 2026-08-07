# What broke — a live bug log

Kept **as I hit things**, not reconstructed afterwards. Every entry has what I
did, what I expected, what happened, and whether I could work around it.
Severity is my judgement of impact on an integrator, not on SuperDocs' roadmap.

Environment unless stated otherwise: agent account created via
`POST /v1/agents/signup` on 2026-08-07, free tier (500 ops/month), REST over
`https://api.superdocs.app`, Python 3.13 + httpx, macOS.

Anything I could not reproduce is marked **UNCONFIRMED** and stays in the list
anyway, because a flake an integrator hits once still costs them an afternoon.

---
