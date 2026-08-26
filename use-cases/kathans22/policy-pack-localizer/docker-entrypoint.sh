#!/bin/sh
# Fails fast, before uvicorn ever binds a port, if SUPERDOCS_API_KEY is
# missing or still the placeholder value. Without this, `docker compose up`
# reports both containers healthy and the API answers config-only routes
# (/countries, /packs) just fine — nothing tells a stranger the deployment
# cannot actually talk to SuperDocs until they trigger a rollout and dig a
# clean error message out of a background run's poll response, minutes
# later. This puts the same cause-and-fix message where it will actually be
# seen: `docker compose up`'s own log output, immediately.
set -e

if [ -z "$SUPERDOCS_API_KEY" ] || [ "$SUPERDOCS_API_KEY" = "your-key-here" ]; then
    echo "==============================================================" >&2
    echo "ERROR: SUPERDOCS_API_KEY is not set." >&2
    echo "Fix: copy .env.example to .env in use-cases/kathans22/policy-pack-localizer/" >&2
    echo "and set SUPERDOCS_API_KEY to your real SuperDocs key (starts with 'sk_')," >&2
    echo "then re-run: docker compose up" >&2
    echo "==============================================================" >&2
    exit 1
fi

exec uvicorn localizer.api.app:app --host 0.0.0.0 --port 8000
