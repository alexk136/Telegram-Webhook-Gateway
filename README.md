![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Framework](https://img.shields.io/badge/framework-FastAPI-009688)
![Telegram](https://img.shields.io/badge/platform-Telegram-blue)
![Queue](https://img.shields.io/badge/queue-SQLite-lightgrey)
![Deploy](https://img.shields.io/badge/deploy-Railway-purple)
![Docker](https://img.shields.io/badge/docker-supported-blue)

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/telegram-webhook-gateway?referralCode=nIQTyp&utm_medium=integration&utm_source=template&utm_campaign=generic)

# 🚀 Telegram Webhook Gateway

A production-ready Telegram webhook gateway with durable queueing, retries, multi-target fan-out, and HMAC-signed delivery.

Designed for reliability, security, and easy deployment on modern PaaS platforms or self-hosted environments.

## ✨ Why This Exists

**Telegram webhooks are fast — but not reliable by default.**

This gateway adds:

- 🗄 **Durable event storage** — SQLite queue survives restarts
- 🔁 **Automatic retries** — exponential backoff on failures
- 🔀 **Multi-consumer delivery** — fan-out to many backends
- 🔐 **Security guarantees** — HMAC signatures, secret tokens, rate limiting
- 📊 **Observability** — `/health` and `/stats` endpoints

So you can safely connect Telegram bots to real backend systems, just like Stripe or GitHub webhooks.

## 🔑 Key Features

- ⚡ **FastAPI** + **aiogram v3** — modern async Python
- 🗄 **SQLite queue** — persistent, PaaS-friendly storage
- 🔁 **Retry logic** — configurable retries with exponential backoff
- 🔀 **Fan-out** — send one event to multiple webhooks
- 🔐 **HMAC signing** — `X-Gateway-Signature` header
- 🛡️ **Access control** — public mode or authorized chat IDs
- ⏱️ **Rate limiting** — per-chat throttling
- 📊 **Stats API** — queue depth, uptime
- 🚆 **PaaS-ready** — works on Railway, Fly.io, Render, or self-hosted

## 🏗 Architecture

```
Telegram Bot API
       ↓
FastAPI Webhook (returns 200 OK immediately)
       ↓
SQLite Queue (durable storage)
       ↓
Background Worker (processes queued events)
       ├─→ Webhook A
       ├─→ Webhook B
       └─→ Webhook C
```

If any target fails → automatic retries with backoff.
If all retries exhausted → event dropped (logged).

## 📦 Event Payload Example

Every forwarded event looks like:

```json
{
  "event": "message",
  "platform": "telegram",
  "chat_id": 1234567890,
  "user_id": 1234567890,
  "username": "username",
  "timestamp": 1772040230,
  "text": "Hello Gateway",
  "raw": {
    "message_id": 123,
    "date": 1772040230,
    "from": { "..." : "..." }
  }
}
```

## 🔐 Webhook Signature Verification

If `OUTBOUND_SECRET` is set, every forwarded request includes:

```
X-Gateway-Signature: <hmac-sha256-hex>
```

**Verify on receiver side (Python):**

```python
import hmac
import hashlib

def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

## ⚙️ Configuration

Copy `.env.example` → `.env` and edit values:

```bash
# Telegram
BOT_TOKEN=123456:ABCDEF
TELEGRAM_SECRET_TOKEN=supersecret

# Webhook targets (choose one)
TARGET_WEBHOOK_URL=https://example.com/webhook
# OR for multiple targets:
# TARGET_WEBHOOK_URLS=https://a.com/webhook,https://b.com/webhook

# Access control
PUBLIC_MODE=false
AUTHORIZED_CHAT_IDS=123456789,987654321

# Rate limiting
RATE_LIMIT_PER_MIN=30
MAX_BODY_SIZE_KB=512

# Queue backend
QUEUE_BACKEND=sqlite
SQLITE_PATH=./events.db

# Retry strategy
MAX_RETRIES=5
BASE_RETRY_DELAY_SEC=2

# Pull API
PULL_API_TOKEN=change_me
MAX_PULL_RETRIES=5

# Outbound webhook signature (optional)
OUTBOUND_SECRET=your_secret_here
```

**Configuration Details:**

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | — | Telegram bot token (required) |
| `TELEGRAM_SECRET_TOKEN` | — | Telegram webhook secret (optional, for security) |
| `TARGET_WEBHOOK_URL` | — | Single webhook endpoint |
| `TARGET_WEBHOOK_URLS` | — | Comma-separated list of endpoints |
| `PUBLIC_MODE` | `false` | Accept messages from any chat? |
| `AUTHORIZED_CHAT_IDS` | — | Comma-separated chat IDs (if not public) |
| `RATE_LIMIT_PER_MIN` | `30` | Max messages per chat per minute |
| `MAX_BODY_SIZE_KB` | `512` | Max incoming message size |
| `SQLITE_PATH` | `./events.db` | Queue database location |
| `MAX_RETRIES` | `5` | Retry attempts before dropping |
| `BASE_RETRY_DELAY_SEC` | `2` | Initial retry delay (exponential) |
| `PULL_API_TOKEN` | — | Bearer token for `/api/pull`, `/api/ack`, `/api/nack`, `/api/pull/stats` |
| `MAX_PULL_RETRIES` | `5` | Max pull retries before message moves to `dead` |
| `OUTBOUND_SECRET` | — | HMAC secret for outbound signatures |

## 🔀 Multi-Target Fan-Out

Send the same event to multiple backends:

```env
TARGET_WEBHOOK_URLS=https://service-a.com/webhook,https://service-b.com/webhook,https://service-c.com/webhook
```

**Behavior:**

- All targets receive identical payloads
- Same `X-Gateway-Signature` for all
- If any target fails → all are retried together
- Event is only deleted after all targets succeed

## 🚆 Deploy on Railway

Railway is recommended because it provides **free HTTPS** (required by Telegram).

### 1. One-click deploy

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/telegram-webhook-gateway?referralCode=nIQTyp&utm_medium=integration&utm_source=template&utm_campaign=generic)

This will:
- create a new Railway project
- attach a persistent volume automatically
- deploy the service with SQLite ready to use

The SQLite database is created automatically on first run and persists across restarts.

### 2. Set environment variables

In Railway → Variables tab:

```env
BOT_TOKEN=your_real_bot_token
TARGET_WEBHOOK_URLS=https://webhook.site/your-id,https://your-backend.com/webhook
TELEGRAM_SECRET_TOKEN=your_secret
OUTBOUND_SECRET=your_outbound_secret
SQLITE_PATH=/data/events.db
```

### 3. Register webhook with Telegram

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -d "url=https://your-app.up.railway.app/telegram/webhook" \
  -d "secret_token=your_secret"
```

Verify:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

## 📊 API Endpoints

### Health Check

```
GET /health
```

Response:

```json
{
  "status": "healthy"
}
```

### Root (Info)

```
GET /
```

Response:

```json
{
  "status": "ok",
  "service": "telegram-webhook-gateway",
  "public_mode": false
}
```

### Statistics

```
GET /stats
```

Response:

```json
{
  "queued": 5,
  "dead_count": 1,
  "uptime_sec": 3600
}
```

### Pull Queue Statistics

```
GET /api/pull/stats
Authorization: Bearer <PULL_API_TOKEN>
```

Optional filter by bot:

```
GET /api/pull/stats?bot_id=<bot_id>
Authorization: Bearer <PULL_API_TOKEN>
```

Response:

```json
{
  "pull_inbox": {
    "bot_id": "123456",
    "new_count": 14,
    "leased_count": 3,
    "acked_count": 248,
    "dead_count": 2,
    "expired_leases": 1
  },
  "generated_at": "2026-03-03T17:00:00Z"
}
```

## 🧪 Local Development

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run with uvicorn

```bash
uvicorn app.main:app --reload
```

Server runs at `http://localhost:8000`

### Test the webhook locally

```bash
# Forward ngrok tunnel to localhost:8000
ngrok http 8000

# Register ngrok URL with Telegram
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://your-ngrok-url/telegram/webhook" \
  -d "secret_token=test"
```

## 🐳 Docker

Build and run:

```bash
docker build -t telegram-webhook-gateway .
docker run -p 8000:8000 -e BOT_TOKEN=... telegram-webhook-gateway
```

## 📝 Logging & Monitoring

Worker logs:

```
🟢 WORKER STARTED
✅ Sent event 1
🔁 Retry 1 for event 2
❌ Dropped event 3 after retries
```

Check queue depth:

```bash
curl http://localhost:8000/stats | jq .queued
```

## 🛠 Planned Features

- [ ] Admin endpoints (queue inspection, replay)
- [ ] Dead-letter queue for failed events
- [ ] Per-target delivery metrics
- [ ] Admin authentication
- [ ] Webhook retry dashboard

Contributions welcome! ❤️

## 📄 License

MIT — use freely, build cool things.

---

**Questions?** Open an issue on GitHub.
