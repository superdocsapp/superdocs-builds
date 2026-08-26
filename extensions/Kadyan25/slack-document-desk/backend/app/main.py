from fastapi import FastAPI, Request
from slack_bolt.adapter.fastapi import SlackRequestHandler

import app.slack.handlers  # noqa: F401  (registers event handlers on import)
from app.slack.app import bolt_app

app = FastAPI(title="Document Desk")
slack_handler = SlackRequestHandler(bolt_app)


@app.post("/slack/events")
async def slack_events(request: Request):
    return await slack_handler.handle(request)


@app.get("/health")
def health():
    return {"status": "ok"}
