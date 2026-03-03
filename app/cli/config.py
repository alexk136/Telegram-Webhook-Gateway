from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse


@dataclass
class CLIConfig:
    server_base_url: str
    pull_api_token: str
    bot_id: str
    consumer_id: str
    batch_size: int
    lease_seconds: int
    poll_interval_sec: float
    local_webhook_url: str | None
    request_timeout_sec: float
    error_backoff_initial_sec: float
    error_backoff_max_sec: float
    error_backoff_multiplier: float

    def masked_dict(self) -> dict[str, object]:
        token = self.pull_api_token
        if len(token) <= 4:
            masked = "***"
        else:
            masked = f"{token[:2]}***{token[-2:]}"
        return {
            "SERVER_BASE_URL": self.server_base_url,
            "PULL_API_TOKEN": masked,
            "BOT_ID": self.bot_id,
            "CONSUMER_ID": self.consumer_id,
            "BATCH_SIZE": self.batch_size,
            "LEASE_SECONDS": self.lease_seconds,
            "POLL_INTERVAL_SEC": self.poll_interval_sec,
            "LOCAL_WEBHOOK_URL": self.local_webhook_url,
            "REQUEST_TIMEOUT_SEC": self.request_timeout_sec,
            "ERROR_BACKOFF_INITIAL_SEC": self.error_backoff_initial_sec,
            "ERROR_BACKOFF_MAX_SEC": self.error_backoff_max_sec,
            "ERROR_BACKOFF_MULTIPLIER": self.error_backoff_multiplier,
        }


def _validate_http_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be a valid http/https URL")
    return value


def load_cli_config(
    *,
    server_base_url: str | None = None,
    pull_api_token: str | None = None,
    bot_id: str | None = None,
    consumer_id: str | None = None,
    batch_size: int | None = None,
    lease_seconds: int | None = None,
    poll_interval_sec: float | None = None,
    local_webhook_url: str | None = None,
    request_timeout_sec: float | None = None,
    error_backoff_initial_sec: float | None = None,
    error_backoff_max_sec: float | None = None,
    error_backoff_multiplier: float | None = None,
    require_local_webhook: bool = False,
) -> CLIConfig:
    server_base_url = (server_base_url or os.getenv("SERVER_BASE_URL", "")).strip()
    pull_api_token = (pull_api_token or os.getenv("PULL_API_TOKEN", "")).strip()
    bot_id = (bot_id or os.getenv("BOT_ID", "")).strip()
    consumer_id = (consumer_id or os.getenv("CONSUMER_ID", "")).strip()
    local_webhook_url = (local_webhook_url or os.getenv("LOCAL_WEBHOOK_URL", "")).strip()

    if not pull_api_token:
        raise ValueError("PULL_API_TOKEN is required")
    if not bot_id:
        raise ValueError("BOT_ID is required")
    if not consumer_id:
        raise ValueError("CONSUMER_ID is required")
    if not server_base_url:
        raise ValueError("SERVER_BASE_URL is required")
    _validate_http_url("SERVER_BASE_URL", server_base_url)

    normalized_local_webhook_url: str | None = None
    if local_webhook_url:
        normalized_local_webhook_url = _validate_http_url("LOCAL_WEBHOOK_URL", local_webhook_url)
    elif require_local_webhook:
        raise ValueError("LOCAL_WEBHOOK_URL is required")

    batch_size = batch_size if batch_size is not None else int(os.getenv("BATCH_SIZE", "10"))
    lease_seconds = lease_seconds if lease_seconds is not None else int(os.getenv("LEASE_SECONDS", "30"))
    poll_interval_sec = (
        poll_interval_sec if poll_interval_sec is not None else float(os.getenv("POLL_INTERVAL_SEC", "2.0"))
    )
    request_timeout_sec = (
        request_timeout_sec
        if request_timeout_sec is not None
        else float(os.getenv("REQUEST_TIMEOUT_SEC", "10.0"))
    )
    error_backoff_initial_sec = (
        error_backoff_initial_sec
        if error_backoff_initial_sec is not None
        else float(os.getenv("ERROR_BACKOFF_INITIAL_SEC", "1.0"))
    )
    error_backoff_max_sec = (
        error_backoff_max_sec
        if error_backoff_max_sec is not None
        else float(os.getenv("ERROR_BACKOFF_MAX_SEC", "30.0"))
    )
    error_backoff_multiplier = (
        error_backoff_multiplier
        if error_backoff_multiplier is not None
        else float(os.getenv("ERROR_BACKOFF_MULTIPLIER", "2.0"))
    )

    if batch_size <= 0:
        raise ValueError("BATCH_SIZE must be > 0")
    if lease_seconds <= 0:
        raise ValueError("LEASE_SECONDS must be > 0")
    if poll_interval_sec <= 0:
        raise ValueError("POLL_INTERVAL_SEC must be > 0")
    if request_timeout_sec <= 0:
        raise ValueError("REQUEST_TIMEOUT_SEC must be > 0")
    if error_backoff_initial_sec <= 0:
        raise ValueError("ERROR_BACKOFF_INITIAL_SEC must be > 0")
    if error_backoff_max_sec <= 0:
        raise ValueError("ERROR_BACKOFF_MAX_SEC must be > 0")
    if error_backoff_max_sec < error_backoff_initial_sec:
        raise ValueError("ERROR_BACKOFF_MAX_SEC must be >= ERROR_BACKOFF_INITIAL_SEC")
    if error_backoff_multiplier < 1:
        raise ValueError("ERROR_BACKOFF_MULTIPLIER must be >= 1")

    return CLIConfig(
        server_base_url=server_base_url,
        pull_api_token=pull_api_token,
        bot_id=bot_id,
        consumer_id=consumer_id,
        batch_size=batch_size,
        lease_seconds=lease_seconds,
        poll_interval_sec=poll_interval_sec,
        local_webhook_url=normalized_local_webhook_url,
        request_timeout_sec=request_timeout_sec,
        error_backoff_initial_sec=error_backoff_initial_sec,
        error_backoff_max_sec=error_backoff_max_sec,
        error_backoff_multiplier=error_backoff_multiplier,
    )
