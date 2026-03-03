from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass
class CLIConfig:
    gateway_base_url: str
    pull_api_token: str
    bot_id: str
    consumer_id: str
    pull_limit: int
    lease_seconds: int
    poll_interval_sec: float
    local_webhook_url: str
    local_timeout_sec: float

def load_cli_config(
    *,
    gateway_base_url: str | None = None,
    pull_api_token: str | None = None,
    bot_id: str | None = None,
    consumer_id: str | None = None,
    pull_limit: int | None = None,
    lease_seconds: int | None = None,
    poll_interval_sec: float | None = None,
    local_webhook_url: str | None = None,
    local_timeout_sec: float | None = None,
) -> CLIConfig:
    gateway_base_url = (gateway_base_url or os.getenv("TGW_BASE_URL", "http://127.0.0.1:8000")).strip()
    pull_api_token = (pull_api_token or os.getenv("PULL_API_TOKEN", "")).strip()
    bot_id = (bot_id or os.getenv("CLI_BOT_ID", "")).strip()
    consumer_id = (consumer_id or os.getenv("CLI_CONSUMER_ID", "cli-consumer")).strip()
    local_webhook_url = (
        local_webhook_url or os.getenv("CLI_LOCAL_WEBHOOK_URL", "http://127.0.0.1:8080/webhook")
    ).strip()

    if not pull_api_token:
        raise ValueError("PULL_API_TOKEN is required")
    if not bot_id:
        raise ValueError("CLI_BOT_ID is required")
    if not consumer_id:
        raise ValueError("CLI_CONSUMER_ID must not be empty")
    if not gateway_base_url:
        raise ValueError("TGW_BASE_URL must not be empty")
    if not local_webhook_url:
        raise ValueError("CLI_LOCAL_WEBHOOK_URL must not be empty")

    pull_limit = pull_limit if pull_limit is not None else int(os.getenv("CLI_PULL_LIMIT", "10"))
    lease_seconds = lease_seconds if lease_seconds is not None else int(os.getenv("CLI_LEASE_SECONDS", "30"))
    poll_interval_sec = (
        poll_interval_sec if poll_interval_sec is not None else float(os.getenv("CLI_POLL_INTERVAL_SEC", "2.0"))
    )
    local_timeout_sec = (
        local_timeout_sec if local_timeout_sec is not None else float(os.getenv("CLI_LOCAL_TIMEOUT_SEC", "10.0"))
    )

    if pull_limit <= 0:
        raise ValueError("CLI_PULL_LIMIT must be > 0")
    if lease_seconds <= 0:
        raise ValueError("CLI_LEASE_SECONDS must be > 0")
    if poll_interval_sec <= 0:
        raise ValueError("CLI_POLL_INTERVAL_SEC must be > 0")
    if local_timeout_sec <= 0:
        raise ValueError("CLI_LOCAL_TIMEOUT_SEC must be > 0")

    return CLIConfig(
        gateway_base_url=gateway_base_url,
        pull_api_token=pull_api_token,
        bot_id=bot_id,
        consumer_id=consumer_id,
        pull_limit=pull_limit,
        lease_seconds=lease_seconds,
        poll_interval_sec=poll_interval_sec,
        local_webhook_url=local_webhook_url,
        local_timeout_sec=local_timeout_sec,
    )
