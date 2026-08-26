#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, SUPERDOCS_API_KEY before the Slack/SuperDocs integration will work."
fi

docker compose up --build -d

echo ""
echo "Backend applies migrations automatically on startup (see backend/entrypoint.sh)."
echo "Waiting a few seconds for everything to come up..."
sleep 5

echo ""
echo "Ready:"
echo "  Backend:  http://localhost:8010"
echo "  Health:   http://localhost:8010/health"
echo "  Slack events endpoint: http://localhost:8010/slack/events (point your Slack app's Request URL here via a tunnel, e.g. ngrok)"
echo ""
echo "Logs: docker compose logs -f"
