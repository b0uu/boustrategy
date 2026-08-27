import hashlib
from pathlib import Path

from app.schemas.live_execution import ExecutionProfile, LiveProfilesConfig


def load_live_profiles(path: str | Path) -> LiveProfilesConfig:
    return LiveProfilesConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))


def get_live_profile(config: LiveProfilesConfig, execution_profile_id: str) -> ExecutionProfile:
    for profile in config.profiles:
        if profile.execution_profile_id == execution_profile_id:
            return profile
    raise ValueError(f"unknown execution profile {execution_profile_id}")


def account_fingerprint(account_identifier: str) -> str:
    normalized = account_identifier.strip()
    if not normalized:
        raise ValueError("account identifier cannot be empty")
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def public_profile_status(config: LiveProfilesConfig) -> list[dict[str, object]]:
    return [
        {
            "execution_profile_id": profile.execution_profile_id,
            "agent_provider": profile.agent_provider.value,
            "account_alias": profile.account_alias,
            "account_bound": bool(profile.broker_account_fingerprint),
            "enabled": profile.enabled,
            "max_order_notional": profile.max_order_notional,
            "require_human_approval": profile.require_human_approval,
        }
        for profile in config.profiles
    ]
