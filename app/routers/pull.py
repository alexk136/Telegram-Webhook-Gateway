import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

import app.state as state
from app.config import settings
from app.contracts.pull import (
    PullMessageContract,
    PullRequestContract,
    PullResponseContract,
    now_utc_iso,
    to_utc_iso,
)


bearer_scheme = HTTPBearer(auto_error=False)


async def require_pull_api_auth(
    authorization: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    expected = settings.PULL_API_TOKEN
    if not expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if authorization is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if authorization.scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.credentials.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(tags=["pull"], dependencies=[Depends(require_pull_api_auth)])


class AckRejected(BaseModel):
    message_id: int = Field(..., description="Message id that could not be acked.")
    reason: str = Field(..., description="Reason for rejection.")


class AckResponse(BaseModel):
    ok: bool = Field(..., examples=[True])
    acked_ids: list[int] = Field(..., description="Successfully acked message ids.")
    already_acked_ids: list[int] = Field(..., description="Ids already acked previously.")
    rejected: list[AckRejected] = Field(..., description="Ids rejected with reasons.")


class AckRequest(BaseModel):
    consumer_id: str = Field(
        default="default-consumer",
        description="Consumer id that owns the lease. Defaults to default-consumer.",
        examples=["default-consumer"],
    )
    message_ids: list[int] = Field(
        default_factory=list,
        description="Leased message ids to acknowledge. Empty list is allowed (no-op).",
        examples=[[101, 102]],
    )


class NackResultItem(BaseModel):
    message_id: int = Field(..., description="Message id processed by nack.")
    status: str = Field(..., description="nacked | skipped")
    reason: str | None = Field(default=None, description="Optional processing detail.")


class NackResponse(BaseModel):
    ok: bool = Field(..., examples=[True])
    requested: int = Field(..., description="Count of ids requested for nack.")
    nacked: int = Field(..., description="Count of ids moved back to processing queue.")
    skipped: int = Field(..., description="Count of ids that were skipped.")
    results: list[NackResultItem] = Field(..., description="Per-id nack processing results.")


class NackRequest(BaseModel):
    consumer_id: str = Field(
        default="default-consumer",
        description="Consumer id that owns the lease. Defaults to default-consumer.",
        examples=["default-consumer"],
    )
    message_ids: list[int] = Field(
        default_factory=list,
        description="Leased message ids to negative-ack. Empty list is allowed (no-op).",
        examples=[[101, 102]],
    )
    error: str | None = Field(default=None, description="Optional error text to save for retry diagnostics.")


class PullInboxStats(BaseModel):
    bot_id: str | None = Field(default=None, description="Resolved bot id used for stats query.")
    new_count: int
    leased_count: int
    acked_count: int
    dead_count: int
    expired_leases: int


class PullStatsResponse(BaseModel):
    pull_inbox: PullInboxStats = Field(..., description="Current pull inbox counters.")
    generated_at: str = Field(..., description="UTC timestamp in ISO-8601.")


def _resolve_pull_bot_id(*, bot_id: str | None, key: str | None) -> str:
    normalized_key = key.strip() if key else None
    if normalized_key and normalized_key not in settings.BOT_CONTEXT_BY_KEY:
        raise HTTPException(status_code=404, detail="Unknown key")

    resolved_bot_id = settings.resolve_bot_id(bot_id=bot_id, bot_key=normalized_key)
    if resolved_bot_id not in settings.known_bot_ids:
        raise HTTPException(status_code=404, detail="Unknown bot_id")
    return resolved_bot_id


@router.get(
    "/api/pull/stats",
    response_model=PullStatsResponse,
    summary="Get Pull Queue Stats",
    description="Returns pull queue counters for resolved bot context. bot_id/key are optional.",
)
async def pull_stats(
    bot_id: str | None = Query(default=None, description="Optional bot id filter."),
    key: str | None = Query(default=None, description="Optional bot key alias; resolved through BOT_CONTEXT_BY_KEY."),
):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    normalized_bot_id = _resolve_pull_bot_id(bot_id=bot_id, key=key)

    stats = await state.queue.pull_inbox_stats(bot_id=normalized_bot_id)
    pull_inbox = PullInboxStats(
        bot_id=normalized_bot_id,
        new_count=stats["new_count"],
        leased_count=stats["leased_count"],
        acked_count=stats["acked_count"],
        dead_count=stats["dead_count"],
        expired_leases=stats["expired_leases"],
    )
    return PullStatsResponse(
        pull_inbox=pull_inbox,
        generated_at=now_utc_iso(),
    )


@router.post(
    "/api/pull",
    response_model=PullResponseContract,
    summary="Pull Messages",
    description="Leases messages from pull queue for a consumer. bot_id/key are optional when defaults exist.",
)
async def pull_messages(payload: PullRequestContract):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    if payload.limit > settings.PULL_MAX_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be <= {settings.PULL_MAX_LIMIT}",
        )

    normalized_bot_id = _resolve_pull_bot_id(bot_id=payload.bot_id, key=payload.key)

    leased = await state.queue.lease_pull(
        consumer_id=payload.consumer_id,
        lease_seconds=payload.lease_seconds,
        limit=payload.limit,
        bot_id=normalized_bot_id,
    )

    messages = [
        PullMessageContract(
            id=item["id"],
            bot_id=item["bot_id"],
            telegram_update_id=item["telegram_update_id"],
            lease_until=to_utc_iso(int(item["lease_until"])),
            payload=item["payload_json"],
        )
        for item in leased
    ]
    return PullResponseContract(
        messages=messages,
        count=len(messages),
        server_time=now_utc_iso(),
    )


@router.post(
    "/api/ack",
    response_model=AckResponse,
    summary="Acknowledge Pulled Messages",
    description="Confirms successful processing for leased messages.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": AckRequest.model_json_schema(),
                    "example": {},
                }
            },
        }
    },
)
async def ack_messages(request: Request):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    consumer_id_raw = payload.get("consumer_id", "default-consumer")
    consumer_id = str(consumer_id_raw).strip() or "default-consumer"

    message_ids_raw = payload.get("message_ids", [])
    if not isinstance(message_ids_raw, list):
        raise HTTPException(status_code=400, detail="message_ids must be an array")

    message_ids: list[int] = []
    for item in message_ids_raw:
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise HTTPException(
                status_code=400,
                detail="message_ids must contain positive integer IDs",
            )
        message_ids.append(item)

    if not message_ids:
        return AckResponse(
            ok=True,
            acked_ids=[],
            already_acked_ids=[],
            rejected=[],
        )

    result = await state.queue.ack_pull_batch(
        message_ids=message_ids,
        consumer_id=consumer_id,
    )
    return AckResponse(
        ok=True,
        acked_ids=result["acked_ids"],
        already_acked_ids=result["already_acked_ids"],
        rejected=[AckRejected(**item) for item in result["rejected"]],
    )


@router.post(
    "/api/nack",
    response_model=NackResponse,
    summary="Negative-Ack Pulled Messages",
    description="Marks leased messages as failed and returns them for retry or dead-lettering.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": NackRequest.model_json_schema(),
                    "example": {},
                }
            },
        }
    },
)
async def nack_messages(request: Request):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    consumer_id_raw = payload.get("consumer_id", "default-consumer")
    consumer_id = str(consumer_id_raw).strip() or "default-consumer"

    message_ids_raw = payload.get("message_ids", [])
    if not isinstance(message_ids_raw, list):
        raise HTTPException(status_code=400, detail="message_ids must be an array")

    message_ids: list[int] = []
    for item in message_ids_raw:
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise HTTPException(
                status_code=400,
                detail="message_ids must contain positive integer IDs",
            )
        message_ids.append(item)

    if not message_ids:
        return NackResponse(
            ok=True,
            requested=0,
            nacked=0,
            skipped=0,
            results=[],
        )

    error_raw = payload.get("error")
    error: str | None = None
    if error_raw is not None:
        error = str(error_raw).strip()
        if not error:
            error = None

    result = await state.queue.nack_pull_batch(
        message_ids=message_ids,
        consumer_id=consumer_id,
        error=error,
        max_pull_retries=settings.MAX_PULL_RETRIES,
    )
    return NackResponse(
        ok=True,
        requested=result["requested"],
        nacked=result["nacked"],
        skipped=result["skipped"],
        results=[NackResultItem(**item) for item in result["results"]],
    )
