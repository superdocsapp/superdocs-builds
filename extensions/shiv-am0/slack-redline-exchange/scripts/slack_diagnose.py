from __future__ import annotations

import asyncio
import sys

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from redline.config import load_settings

WANTED_CHANNEL_NAMES = {"shared", "vendor-internal", "customer-internal"}


async def main() -> None:
    settings = load_settings()
    if not settings.slack_bot_token:
        print(
            "SLACK_BOT_TOKEN is empty in .env -- fill that in first (from OAuth & "
            "Permissions -> Bot User OAuth Token), then re-run this script.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    client = AsyncWebClient(token=settings.slack_bot_token)

    print("=== Workspace ===")
    try:
        auth = await client.auth_test()
    except SlackApiError as exc:
        print(f"auth.test failed: {exc.response['error']}", file=sys.stderr)
        print(
            "Most likely SLACK_BOT_TOKEN is wrong or the app was never installed to "
            "the workspace (OAuth & Permissions -> Install to Workspace).",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    print(f"  team_id:    {auth['team_id']}   (put this in VENDOR_TEAM_ID and CUSTOMER_TEAM_ID)")
    print(f"  team name:  {auth['team']}")
    print(f"  bot user:   {auth['user_id']} ({auth['user']})")

    print("\n=== Channels the bot can see ===")
    print("(the bot must be INVITED to private channels before they show up here --")
    print(" run /invite @your-app-name in each of your 3 channels first)\n")
    matches: dict[str, str] = {}
    cursor = None
    while True:
        try:
            resp = await client.conversations_list(
                types="public_channel,private_channel",
                limit=200,
                cursor=cursor,
            )
        except SlackApiError as exc:
            print(f"conversations.list failed: {exc.response['error']}", file=sys.stderr)
            if exc.response["error"] == "missing_scope":
                print(
                    "Add the 'channels:read' and 'groups:read' bot scopes under "
                    "OAuth & Permissions, then reinstall the app.",
                    file=sys.stderr,
                )
            raise SystemExit(1) from exc
        for channel in resp["channels"]:
            name = channel["name"]
            kind = "private" if channel["is_private"] else "public"
            in_channel = channel.get("is_member", False)
            marker = " <-" if name in WANTED_CHANNEL_NAMES else ""
            print(f"  #{name:<24} {channel['id']:<12} {kind:<8} member={in_channel}{marker}")
            if name in WANTED_CHANNEL_NAMES:
                matches[name] = channel["id"]
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    if matches:
        print("\n=== Suggested .env values (matched by channel name) ===")
        if "shared" in matches:
            print(f"  SHARED_CHANNEL={matches['shared']}")
        if "vendor-internal" in matches:
            print(f"  VENDOR_INTERNAL_CHANNEL={matches['vendor-internal']}")
        if "customer-internal" in matches:
            print(f"  CUSTOMER_INTERNAL_CHANNEL={matches['customer-internal']}")
        missing = WANTED_CHANNEL_NAMES - matches.keys()
        if missing:
            print(f"\n  NOT found (bot not invited yet, or named differently): {sorted(missing)}")
            print("  Run /invite @your-app-name in each of those channels and re-run this script.")

    print("\n=== Workspace members (for SIDE_OVERRIDE_USERS) ===")
    cursor = None
    while True:
        try:
            resp = await client.users_list(limit=200, cursor=cursor)
        except SlackApiError as exc:
            print(f"users.list failed: {exc.response['error']}", file=sys.stderr)
            break
        for member in resp["members"]:
            if member.get("is_bot") or member.get("deleted") or member["id"] == "USLACKBOT":
                continue
            real_name = member.get("real_name") or member.get("name", "?")
            print(f"  {member['id']:<12} {real_name}")
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    print(
        "\nPick two of the IDs above (or invite a second person) and set, e.g.:\n"
        "  SIDE_OVERRIDE_USERS=U0111AAA:vendor,U0222BBB:customer"
    )


if __name__ == "__main__":
    asyncio.run(main())
