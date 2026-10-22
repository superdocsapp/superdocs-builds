from pydantic_settings import BaseSettings, SettingsConfigDict

APPROVAL_POLICIES = ("dual_consent", "proposer_only")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    superdocs_api_key: str = ""
    superdocs_base_url: str = "https://api.superdocs.app"

    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_signing_secret: str = ""

    # Two-workspace (real Slack Connect) mode. Each company runs its own Slack app in
    # its own workspace, so each has its own pair of tokens. Leave these empty to stay
    # in single-workspace mode and use the SLACK_* tokens above.
    vendor_bot_token: str = ""
    vendor_app_token: str = ""
    customer_bot_token: str = ""
    customer_app_token: str = ""

    fake_mode: bool = True
    database_path: str = "./redline.db"

    approval_policy: str = "dual_consent"
    poll_interval_seconds: float = 2.0
    warn_after_seconds: float = 60.0
    max_job_wait_seconds: float = 900.0
    # How long an identical propose request folds into the previous one instead of
    # starting (and billing) a second SuperDocs job. Jobs still in review dedupe
    # regardless of age; this window only covers repeats after one has finished.
    idempotency_window_seconds: float = 120.0

    vendor_team_id: str = "T_VENDOR"
    customer_team_id: str = "T_CUSTOMER"
    vendor_internal_channel: str = "C_INT_VENDOR"
    customer_internal_channel: str = "C_INT_CUSTOMER"
    shared_channel: str = "C_SHARED"

    side_override_users: str = ""

    def _overrides(self) -> dict[str, str]:
        """Parse SIDE_OVERRIDE_USERS ("U123:vendor,U456:customer") into a lookup.

        Slack Connect normally means two separate workspaces, one per company. When
        testing from a single workspace there is only one team_id, so this lets specific
        user IDs be pinned to a side. It is a testing affordance, never the primary
        mechanism: in production the workspace a person belongs to decides their side.
        """
        mapping: dict[str, str] = {}
        for entry in self.side_override_users.split(","):
            entry = entry.strip()
            if not entry:
                continue
            user_id, _, side = entry.partition(":")
            user_id, side = user_id.strip(), side.strip().lower()
            if side not in ("vendor", "customer"):
                raise UnknownSideError(side or entry)
            # Silently letting a later entry win would hand one person both sides on
            # paper while the anti-forgery check still refuses half their clicks --
            # a confusing failure far from its cause. Reject it at config time.
            if user_id in mapping and mapping[user_id] != side:
                raise AmbiguousSideOverrideError(user_id, mapping[user_id], side)
            mapping[user_id] = side
        return mapping

    def side_for_team(self, team_id: str) -> str:
        if team_id == self.vendor_team_id:
            return "vendor"
        if team_id == self.customer_team_id:
            return "customer"
        raise UnknownTeamError(team_id, self.vendor_team_id, self.customer_team_id)

    def side_for(self, team_id: str, user_id: str | None = None) -> str:
        """Resolve which side an actor represents, honouring per-user overrides first."""
        if user_id:
            override = self._overrides().get(user_id)
            if override:
                return override
        return self.side_for_team(team_id)

    @property
    def two_workspace_mode(self) -> bool:
        """True when each company has its own Slack app, i.e. real Slack Connect.

        Both sides must be configured before the mode turns on: a half-configured pair
        would silently post one company's messages with the other company's bot.
        """
        return bool(
            self.vendor_bot_token
            and self.vendor_app_token
            and self.customer_bot_token
            and self.customer_app_token
        )

    def bot_token_for_side(self, side: str) -> str:
        if not self.two_workspace_mode:
            return self.slack_bot_token
        if side == "vendor":
            return self.vendor_bot_token
        if side == "customer":
            return self.customer_bot_token
        raise UnknownSideError(side)

    def app_token_for_side(self, side: str) -> str:
        if not self.two_workspace_mode:
            return self.slack_app_token
        if side == "vendor":
            return self.vendor_app_token
        if side == "customer":
            return self.customer_app_token
        raise UnknownSideError(side)

    def team_id_for_side(self, side: str) -> str:
        if side == "vendor":
            return self.vendor_team_id
        if side == "customer":
            return self.customer_team_id
        raise UnknownSideError(side)

    def side_owning_channel(self, channel_id: str) -> str:
        """Which company's bot is responsible for a given channel.

        The shared channel is deliberately owned by the vendor side. Slack only lets an
        app edit messages it posted itself, and proposal cards are updated in place on
        every decision -- so exactly one bot must own every shared-channel message, or
        the first cross-company update fails.
        """
        if channel_id == self.customer_internal_channel:
            return "customer"
        return "vendor"

    def internal_channel_for(self, side: str) -> str:
        if side == "vendor":
            return self.vendor_internal_channel
        if side == "customer":
            return self.customer_internal_channel
        raise UnknownSideError(side)


class UnknownTeamError(ValueError):
    def __init__(self, team_id: str, vendor_team_id: str, customer_team_id: str):
        super().__init__(
            f"team {team_id!r} is not part of this deal; "
            f"expected {vendor_team_id!r} or {customer_team_id!r}"
        )


class UnknownSideError(ValueError):
    def __init__(self, side: str):
        super().__init__(f"unknown side {side!r}; expected 'vendor' or 'customer'")


class AmbiguousSideOverrideError(ValueError):
    def __init__(self, user_id: str, first: str, second: str):
        super().__init__(
            f"SIDE_OVERRIDE_USERS maps {user_id!r} to both {first!r} and {second!r}. "
            "A single identity cannot act for both parties -- that is exactly what the "
            "dual-consent check exists to prevent. Map this user to one side and use a "
            "second Slack user (or the REST API) for the other."
        )


def load_settings() -> Settings:
    return Settings()
