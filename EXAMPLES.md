# 📍 Примеры конфигурации для разных сценариев

Готовые примеры `.env` для типичных сценариев развертывания.

---

## 1️⃣ Простый сценарий: Один бот, один webhook

**Сценарий:** Telegram бот → Telegram Webhook Gateway → один backend

**.env конфиг:**
```env
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_SECRET_TOKEN=4234092387r82342r

TARGET_WEBHOOK_URL=https://api.example.com/telegram/events

PUBLIC_MODE=true
OUTBOUND_SECRET=
```

**Как это работает:**
```
Telegram → [это приложение] → https://api.example.com/telegram/events
```

---

## 2️⃣ Надежный сценарий: Мультибекенд с подписью

**Сценарий:** Telegram → Gateway → 2+ бекенда с HMAC сигнатурой и повторами

**.env конфиг:**
```env
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_SECRET_TOKEN=secret_from_telegram_setwebhook_call

# Несколько целей (JSON массив)
TARGET_WEBHOOK_URLS=[
  "https://backend1.example.com/telegram/webhook",
  "https://backend2.example.com/telegram/webhook",
  "https://logging.example.com/events"
]

# Безопасность
OUTBOUND_SECRET=your_secret_key_minimum_32_characters_long_here
TELEGRAM_WEBHOOK_PATH=/telegram/webhook

# Надежность
MAX_RETRIES=5
BASE_RETRY_DELAY_SEC=2
FORWARD_TIMEOUT_SEC=15

# Доступ
PUBLIC_MODE=false
RATE_LIMIT_PER_MIN=30
```

**Как работает delivery:**
```
POST https://backend1.example.com/telegram/webhook
  X-Gateway-Signature: <hmac-sha256-hex>
  Content-Type: application/json
  
  {event payload}

POST https://backend2.example.com/telegram/webhook
  X-Gateway-Signature: <hmac-sha256-hex>
  ...

POST https://logging.example.com/events
  ...
```

**Верификация сигнатуры (Python):**
```python
import hmac
import hashlib

def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---

## 3️⃣ Приватный бот: Только авторизованные чаты

**Сценарий:** Telegram бот доступен только для определенных чатов (групп/юзеров)

**.env конфиг:**
```env
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_SECRET_TOKEN=secret_token

TARGET_WEBHOOK_URL=https://private-backend.local/webhook

# КРАЙНЕ ВАЖНО для приватного бота
PUBLIC_MODE=false
AUTHORIZED_CHAT_IDS=123456789,987654321,111222333

# Сигнатура для удостоверения источника
OUTBOUND_SECRET=secret_key_min_32_chars

# Снижен лимит для приватного использования
RATE_LIMIT_PER_MIN=10
MAX_RETRIES=3
```

**Как работает доступ:**
```
Сообщение от chat_id=123456789  ✓ РАЗРЕШЕНО → отправляется на webhook
Сообщение от chat_id=999999999  ✗ ЗАПРЕЩЕНО → игнорируется, логируется
```

---

## 4️⃣ Мультибот: Несколько независимых ботов на одном сервере

**Сценарий:** 3 разных Telegram бота, каждый с собственным webhook путем

**.env конфиг:**
```env
# Основной бот (по умолчанию)
BOT_TOKEN=bot1_token_123456:ABC...

# Маршрутизация многих ботов
BOT_CONTEXT_BY_KEY={
  "sales": "bot2_token_999999:XYZ...",
  "support": "bot3_token_555555:LMN..."
}

# Вебхук пути для каждого бота
TELEGRAM_WEBHOOK_PATH=/telegram/{bot_key}
# или для основного: /telegram/webhook

TARGET_WEBHOOK_URL=https://api.example.com/telegram

RATE_LIMIT_PER_MIN=30
OUTBOUND_SECRET=shared_secret_for_all_bots
```

**Как регистрировать вебхуки в Telegram:**
```bash
# Основной бот (bot_key отсутствует)
curl "https://api.telegram.org/bot$(echo $BOT_TOKEN | cut -d: -f1)/setWebhook?url=https://your-domain.com/telegram/webhook"

# Бот "sales"
curl "https://api.telegram.org/botBOT2_ID/setWebhook?url=https://your-domain.com/telegram/sales"

# Бот "support"
curl "https://api.telegram.org/botBOT3_ID/setWebhook?url=https://your-domain.com/telegram/support"
```

**Как это работает на backend:**
```json
// Событие от основного бота:
{
  "event": "message",
  "platform": "telegram",
  "chat_id": 123456,
  ...
}

// События автоматически различаются по path:
// /telegram/webhook       → основной бот
// /telegram/sales         → bот2
// /telegram/support       → бот3
```

---

## 5️⃣ Production на Railway.app

**Сценарий:** Развертывание на PaaS платформе Railway

**.env для Railway:**
```env
# Railway автоматически задает PORT переменную
# PORT=8000

BOT_TOKEN=${{Secrets.BOT_TOKEN}}
TELEGRAM_SECRET_TOKEN=${{Secrets.TELEGRAM_SECRET_TOKEN}}

# Railway предоставляет публичный URL
TARGET_WEBHOOK_URL=https://${{Railway.PublicDomain}}/telegram/webhook

OUTBOUND_SECRET=${{Secrets.OUTBOUND_SECRET}}

# Railway управляет SSL автоматически
PUBLIC_MODE=false
RATE_LIMIT_PER_MIN=30

# SQLite на Railway
SQLITE_PATH=/data/events.db
QUEUE_BACKEND=sqlite

MAX_RETRIES=5
BASE_RETRY_DELAY_SEC=2
```

**Нужно установить в Railway Secrets:**
- `BOT_TOKEN`
- `TELEGRAM_SECRET_TOKEN`
- `OUTBOUND_SECRET`

---

## 6️⃣ Docker Swarm / Kubernetes-ready

**Сценарий:** Распределенное развертывание

**.env конфиг:**
```env
BOT_TOKEN=${BOT_TOKEN}
TELEGRAM_SECRET_TOKEN=${TELEGRAM_SECRET_TOKEN}

# Несколько целей (каждая в отдельном сервисе)
TARGET_WEBHOOK_URLS=[
  "http://backend-service-1:8080/webhook",
  "http://backend-service-2:8080/webhook",
  "http://logging-service:9200/events"
]

OUTBOUND_SECRET=${OUTBOUND_SECRET}
SQLITE_PATH=/data/events.db

# Увеличенные таймауты для сетевых задержек
FORWARD_TIMEOUT_SEC=30
MAX_RETRIES=5
BASE_RETRY_DELAY_SEC=3

PUBLIC_MODE=false
RATE_LIMIT_PER_MIN=50
```

**docker-compose.yml для Swarm:**
```yaml
version: '3.8'

services:
  telegram-gateway:
    image: my-registry.com/telegram-gateway:latest
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    env_file:
      - .env
    volumes:
      - gateway-data:/data
    networks:
      - backend-network

networks:
  backend-network:
    driver: overlay

volumes:
  gateway-data:
    driver: local
```

---

## 7️⃣ Минимальный (легкие боты)

**Сценарий:** Автоматизированный бот с одной целью, минимальные требования

**.env конфиг:**
```env
BOT_TOKEN=123456:ABC...
TARGET_WEBHOOK_URL=https://lambda.example.com/telegram

PUBLIC_MODE=true
MAX_RETRIES=2
BASE_RETRY_DELAY_SEC=1
```

---

## 8️⃣ Максимальный (enterprise)

**Сценарий:** Критичное production приложение с полным мониторингом

**.env конфиг:**
```env
# Основное
BOT_TOKEN=123456:ABC...
TELEGRAM_SECRET_TOKEN=strong_token_secret

# Многие целевые вебхуки
TARGET_WEBHOOK_URLS=[
  "https://primary-backend.example.com/telegram",
  "https://backup-backend.example.com/telegram",
  "https://archive-logging.example.com/events",
  "https://monitoring.datadog.com/webhook"
]

# Безопасность
OUTBOUND_SECRET=enterprise_grade_secret_32_plus_chars
TELEGRAM_WEBHOOK_PATH=/telegram/webhook
PUBLIC_MODE=false
AUTHORIZED_CHAT_IDS=admin_chat_1,admin_chat_2

# Надежность и производительность
MAX_RETRIES=7
BASE_RETRY_DELAY_SEC=3
FORWARD_TIMEOUT_SEC=30
RATE_LIMIT_PER_MIN=100
MAX_BODY_SIZE_KB=1024

# Хранилище
QUEUE_BACKEND=sqlite
SQLITE_PATH=/data/events.db

# Очистка и обслуживание
PULL_INBOX_ACKED_RETENTION_DAYS=30
PULL_INBOX_DEAD_RETENTION_DAYS=90
PULL_INBOX_CLEANUP_INTERVAL_SEC=600
PULL_INBOX_CLEANUP_BATCH_SIZE=5000

# Pull API для ручного извлечения событий
PULL_API_TOKEN=enterprise_pull_token
PULL_MAX_LIMIT=1000
MAX_PULL_RETRIES=10
```

---

## 🔄 Переключение между конфигурациями

Если тебе нужно быстро переключаться между разными конфигами:

```bash
# Сохрани разные .env файлы
cp .env .env.production
cp .env .env.staging
cp .env .env.development

# Переключайся между ними
cp .env.production .env && docker compose restart

# Или используй docker compose --env-file
docker compose --env-file .env.production up -d
```

---

## ✅ Проверка конфигурации

```bash
# Валидировать синтаксис .env
python3 -c "
import re
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#'):
            if '=' not in line:
                print(f'❌ Bad line: {line}')
            else:
                key, val = line.split('=', 1)
                print(f'✓ {key}')
"

# Проверить требуемые переменные
grep -E "^(BOT_TOKEN|TARGET_WEBHOOK_URL)=" .env || \
  echo "⚠️ Missing required variables!"
```

---

**Выбери конфиг подходящий для твоего случая и модифицируй под свои нужды!** 🚀
