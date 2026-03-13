import json
from typing import Set, Dict, Callable
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, validator


class Settings(BaseSettings):
    BOT_TOKEN: str = Field(..., description="Telegram bot token")
    TELEGRAM_WEBHOOK_PATH: str = "/telegram/webhook"
    TELEGRAM_SECRET_TOKEN: str | None = None

    TARGET_WEBHOOK_URL: str | None = Field(
        None, description="Default webhook target"
    )

    TARGET_WEBHOOK_URLS: str | None = None

    PUBLIC_MODE: bool = False
    AUTHORIZED_CHAT_IDS: Set[int] = set()
    RATE_LIMIT_PER_MIN: int = 30
    MAX_BODY_SIZE_KB: int = 512

    FORWARD_TIMEOUT_SEC: int = 10

    QUEUE_BACKEND: str = "sqlite"
    SQLITE_PATH: str = "./events.db"

    MAX_RETRIES: int = 5
    BASE_RETRY_DELAY_SEC: int = 2
    PULL_MAX_LIMIT: int = 100
    MAX_PULL_RETRIES: int = 5
    PULL_API_TOKEN: str | None = None
    PULL_INBOX_ACKED_RETENTION_DAYS: int = 7
    PULL_INBOX_DEAD_RETENTION_DAYS: int = 30
    PULL_INBOX_CLEANUP_BATCH_SIZE: int = 1000
    PULL_INBOX_CLEANUP_INTERVAL_SEC: int = 300

    DEFAULT_CHAT_ID: int | None = None
    DEFAULT_BOT_KEY: str | None = None
    BOT_TOKEN_BY_KEY: Dict[str, str] = Field(
        default_factory=dict,
        description="Optional mapping bot_key -> bot_token for /api/send",
    )
    DEFAULT_CHAT_ID_BY_KEY: Dict[str, int] = Field(
        default_factory=dict,
        description="Optional mapping bot_key -> default chat_id",
    )

    OUTBOUND_SECRET: str | None = None
    BOT_CONTEXT_BY_KEY: Dict[str, str] = Field(
        default_factory=dict,
        description="Optional mapping bot_key -> bot_id for multi-bot webhook routes",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )

    @validator("AUTHORIZED_CHAT_IDS", pre=True)
    def parse_chat_ids(cls, v):
        if not v:
            return set()
        if isinstance(v, set):
            return v
        return {int(x.strip()) for x in str(v).split(",")}

    @validator("BOT_CONTEXT_BY_KEY", pre=True)
    def parse_bot_context_map(cls, v):
        return _parse_str_mapping(v, field_name="BOT_CONTEXT_BY_KEY")

    @validator("BOT_TOKEN_BY_KEY", pre=True)
    def parse_bot_token_map(cls, v):
        return _parse_str_mapping(v, field_name="BOT_TOKEN_BY_KEY")

    @validator("DEFAULT_CHAT_ID_BY_KEY", pre=True)
    def parse_default_chat_map(cls, v):
        return _parse_mapping(
            v,
            field_name="DEFAULT_CHAT_ID_BY_KEY",
            value_cast=int,
        )

    @validator("DEFAULT_BOT_KEY")
    def validate_default_bot_key(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if not value:
            return None
        return value

    @validator("DEFAULT_CHAT_ID")
    def validate_default_chat_id(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v == 0:
            raise ValueError("DEFAULT_CHAT_ID must not be 0")
        return v

    @property
    def default_bot_id(self) -> str:
        if self.DEFAULT_BOT_KEY:
            mapped = self.BOT_CONTEXT_BY_KEY.get(self.DEFAULT_BOT_KEY)
            if mapped:
                return mapped
        token_prefix = self.BOT_TOKEN.split(":", 1)[0].strip()
        if not token_prefix:
            raise ValueError("BOT_TOKEN must include bot id prefix before ':'")
        return token_prefix

    def resolve_bot_id(self, *, bot_id: str | None = None, bot_key: str | None = None) -> str:
        if bot_id is not None:
            resolved = str(bot_id).strip()
            if resolved:
                return resolved
        if bot_key is not None:
            key = str(bot_key).strip()
            if key:
                mapped = self.BOT_CONTEXT_BY_KEY.get(key)
                if mapped:
                    return mapped
        return self.default_bot_id

    def resolve_bot_token(self, *, bot_key: str | None = None) -> str:
        if bot_key is not None:
            key = str(bot_key).strip()
            if key:
                mapped = self.BOT_TOKEN_BY_KEY.get(key)
                if mapped:
                    return mapped
        return self.BOT_TOKEN

    def resolve_default_chat_id(self, *, bot_key: str | None = None) -> int | None:
        if bot_key is not None:
            key = str(bot_key).strip()
            if key and key in self.DEFAULT_CHAT_ID_BY_KEY:
                return self.DEFAULT_CHAT_ID_BY_KEY[key]
        return self.DEFAULT_CHAT_ID

    @validator("MAX_PULL_RETRIES")
    def validate_max_pull_retries(cls, v: int) -> int:
        if v < 0:
            raise ValueError("MAX_PULL_RETRIES must be >= 0")
        return v

    @validator("PULL_API_TOKEN")
    def validate_pull_api_token(cls, v: str | None) -> str | None:
        if v is None:
            return None
        token = v.strip()
        if not token:
            return None
        return token

    @validator("PULL_INBOX_ACKED_RETENTION_DAYS", "PULL_INBOX_DEAD_RETENTION_DAYS")
    def validate_pull_inbox_retention_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError("PULL_INBOX retention days must be >= 0")
        return v

    @validator("PULL_INBOX_CLEANUP_BATCH_SIZE", "PULL_INBOX_CLEANUP_INTERVAL_SEC")
    def validate_positive_cleanup_config(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("PULL_INBOX cleanup config values must be > 0")
        return v

    @property
    def target_urls(self) -> list[str]:
        """
        Fan-out logic:
        - If TARGET_WEBHOOK_URLS is set → use multiple
        - Else → fallback to TARGET_WEBHOOK_URL
        """
        if self.TARGET_WEBHOOK_URLS:
            return [
                u.strip()
                for u in self.TARGET_WEBHOOK_URLS.split(",")
                if u.strip()
            ]
        return [self.TARGET_WEBHOOK_URL]

    @property
    def known_bot_ids(self) -> set[str]:
        bot_ids = {bot_id for bot_id in self.BOT_CONTEXT_BY_KEY.values() if bot_id}
        token_prefix = self.BOT_TOKEN.split(":", 1)[0].strip()
        if token_prefix:
            bot_ids.add(token_prefix)
        return bot_ids


def _parse_str_mapping(v, *, field_name: str) -> Dict[str, str]:
    return _parse_mapping(v, field_name=field_name, value_cast=str)


def _parse_mapping(v, *, field_name: str, value_cast: Callable[[str], object]) -> Dict[str, object]:
    if not v:
        return {}

    def cast_and_validate(raw_key: object, raw_value: object) -> tuple[str, object]:
        key = str(raw_key).strip()
        value_text = str(raw_value).strip()
        if not key or not value_text:
            raise ValueError(f"{field_name} contains empty key or value")
        return key, value_cast(value_text)

    if isinstance(v, dict):
        result: Dict[str, object] = {}
        for raw_key, raw_value in v.items():
            key, value = cast_and_validate(raw_key, raw_value)
            result[key] = value
        return result

    raw = str(v).strip()
    if not raw:
        return {}

    if raw.startswith("{"):
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} JSON must be an object")
        result: Dict[str, object] = {}
        for raw_key, raw_value in parsed.items():
            key, value = cast_and_validate(raw_key, raw_value)
            result[key] = value
        return result

    result: Dict[str, object] = {}
    for item in raw.split(","):
        pair = item.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(
                f"{field_name} must be 'key:value,key2:value2'"
            )
        raw_key, raw_value = pair.split(":", 1)
        key, value = cast_and_validate(raw_key, raw_value)
        result[key] = value
    return result


settings = Settings()
