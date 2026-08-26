from slack_bolt import App

from app.config import settings

# token_verification_enabled=False so the process can boot (and be developed/tested
# offline) before a real Slack app/bot token exists — Bolt would otherwise call
# auth.test at construction time and crash on a placeholder token.
bolt_app = App(
    token=settings.slack_bot_token,
    signing_secret=settings.slack_signing_secret,
    token_verification_enabled=False,
    process_before_response=True,
)
