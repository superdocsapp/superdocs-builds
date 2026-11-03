from dataclasses import dataclass

from app.gateway.policy import (
    DEFAULT_GATEWAY_POLICY,
    GatewayPolicyConfig,
    ToolPolicy,
)
from app.gateway.quota import DEFAULT_QUOTA_MANAGER, QuotaManager
from app.gateway.sensitive import SensitiveAction, scan_sensitive_content


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    status_code: int
    error: str | None = None
    categories: tuple[str, ...] = ()
    content: str = ""


class GatewayPolicyPipeline:
    """Apply the gateway policy in a deterministic order.

    Tool allowlisting is checked first. Sensitive-content policy is checked
    next, so rejected sensitive requests do not consume quota. Quota is
    consumed only after all policy checks pass.
    """

    def __init__(
        self,
        *,
        tool_policy: ToolPolicy | None = None,
        quota_manager: QuotaManager | None = None,
        policy: GatewayPolicyConfig | None = None,
    ) -> None:
        self.policy = policy or DEFAULT_GATEWAY_POLICY
        self.tool_policy = tool_policy or self.policy.tool_policy
        self.quota_manager = quota_manager or DEFAULT_QUOTA_MANAGER

    def evaluate(
        self,
        *,
        team_id: str,
        tool: str,
        content: str = "",
    ) -> PolicyDecision:
        if not self.tool_policy.is_allowed(tool):
            return PolicyDecision(
                allowed=False,
                status_code=403,
                error="TOOL_NOT_ALLOWED",
            )

        if self.policy.sensitive_policy.enabled:
            action = SensitiveAction(self.policy.sensitive_policy.action)
            result = scan_sensitive_content(content, action=action)
            categories = tuple(
                sorted({match.category for match in result.matches})
            )

            if not result.allowed:
                return PolicyDecision(
                    allowed=False,
                    status_code=403,
                    error="SENSITIVE_CONTENT_BLOCKED",
                    categories=categories,
                    content=result.content,
                )

            content = result.content

        if not self.quota_manager.check_and_consume(team_id):
            return PolicyDecision(
                allowed=False,
                status_code=429,
                error="TEAM_QUOTA_EXCEEDED",
                content=content,
            )

        return PolicyDecision(
            allowed=True,
            status_code=200,
            content=content,
        )


DEFAULT_GATEWAY_POLICY_PIPELINE = GatewayPolicyPipeline()
