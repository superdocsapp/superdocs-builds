from dataclasses import dataclass, field


@dataclass
class TeamQuota:
    limit: int
    used: int = 0


@dataclass
class QuotaManager:
    quotas: dict[str, TeamQuota] = field(default_factory=dict)

    def check_and_consume(self, team: str) -> bool:
        quota = self.quotas.get(team)
        if quota is None or quota.used >= quota.limit:
            return False
        quota.used += 1
        return True

    def remaining(self, team: str) -> int:
        quota = self.quotas.get(team)
        if quota is None:
            return 0
        return max(quota.limit - quota.used, 0)


def build_quota_manager(quota_limits: dict[str, int]) -> QuotaManager:
    return QuotaManager(
        quotas={
            team: TeamQuota(limit=limit)
            for team, limit in quota_limits.items()
        }
    )


from app.gateway.policy import DEFAULT_GATEWAY_POLICY

DEFAULT_QUOTA_MANAGER = build_quota_manager(DEFAULT_GATEWAY_POLICY.quotas)
