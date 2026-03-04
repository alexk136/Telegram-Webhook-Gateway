# 📦 Инструкция по развертыванию Telegram Webhook Gateway в Docker

Полное руководство по развертыванию приложения на сервере с использованием Docker.

---

## 🔰 Предварительные требования

### На сервере должны быть установлены:
- **Docker** (≥20.10)
- **Docker Compose** (≥1.29) — опционально, для orchestration
- **Git** — для клонирования репозитория

### Проверка установки:
```bash
docker --version
docker compose --version
```

---

## 📋 Подготовка к развертыванию

### 1. Клонирование репозитория

```bash
cd /opt  # или любой другой выбранный каталог
git clone https://github.com/you/Telegram-Webhook-Gateway.git
cd Telegram-Webhook-Gateway
```

### 2. Создание файла конфигурации `.env`

Создай файл `.env` в корне проекта:

```bash
cp .env.example .env  # если есть шаблон
# или создай вручную:
nano .env
```

**Минимальная конфигурация:**

```env
# ===== REQUIRED =====
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_SECRET_TOKEN=your_secret_token_from_telegram

# ===== OUTBOUND CONFIG =====
# Одна цель:
TARGET_WEBHOOK_URL=https://your-backend.com/telegram/webhook

# ИЛИ несколько целей (JSON):
# TARGET_WEBHOOK_URLS=[
#   "https://backend1.com/webhook",
#   "https://backend2.com/webhook"
# ]

# ===== SECURITY =====
OUTBOUND_SECRET=your_hmac_secret_key_min_32_chars_strong

# ===== ACCESS CONTROL =====
PUBLIC_MODE=false
# AUTHORIZED_CHAT_IDS=123456789,987654321,111222333

# ===== RATE LIMITING =====
RATE_LIMIT_PER_MIN=30

# ===== RETRY POLICY =====
MAX_RETRIES=5
BASE_RETRY_DELAY_SEC=2
FORWARD_TIMEOUT_SEC=10

# ===== DATABASE =====
SQLITE_PATH=/app/data/events.db

# ===== PORT =====
PORT=8000

# ===== OPTIONAL: PULL API ===== 
# PULL_API_TOKEN=your_pull_api_token
# PULL_MAX_LIMIT=100
# PULL_INBOX_CLEANUP_INTERVAL_SEC=300
```

### 3. Генерация безопасного токена для HMAC (опционально)

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 🐳 Развертывание с Docker

### Вариант 1: Простый запуск одного контейнера

#### Шаг 1: Построение образа

```bash
docker build -t telegram-webhook-gateway:latest .
```

#### Шаг 2: Запуск контейнера

```bash
docker run -d \
  --name telegram-gateway \
  -p 8000:8000 \
  --env-file .env \
  -v /opt/Telegram-Webhook-Gateway/data:/app/data \
  telegram-webhook-gateway:latest
```

**Объяснение параметров:**
- `-d` — запуск в фоне
- `--name telegram-gateway` — имя контейнера
- `-p 8000:8000` — маппирование портов (хост:контейнер)
- `--env-file .env` — загрузка переменных окружения из файла
- `-v /opt/.../data:/app/data` — монтирование тома для сохранения БД SQLite
- `telegram-webhook-gateway:latest` — образ

#### Шаг 3: Проверка статуса

```bash
docker ps | grep telegram-gateway
docker logs -f telegram-gateway
```

---

### Вариант 2: Docker Compose (рекомендуется для production)

#### Шаг 1: Создание `docker-compose.yml`

```yaml
version: '3.8'

services:
  telegram-gateway:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: telegram-webhook-gateway
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      PORT: 8000
    env_file:
      - .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    # Опционально: логирование
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  data:
  logs:
```

#### Шаг 2: Запуск через Docker Compose

```bash
# Запуск в фоне
docker compose up -d

# Просмотр логов
docker compose logs -f telegram-gateway

# Остановка
docker compose down

# Пересборка образа
docker compose up -d --build
```

---

## 🌐 Настройка Nginx как reverse proxy

### Вариант: Nginx + SSL (Let's Encrypt)

#### Шаг 1: Установка Nginx

```bash
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
```

#### Шаг 2: Конфиг Nginx (`/etc/nginx/sites-available/telegram-gateway`)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Redirect HTTP → HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # SSL параметры
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Логирование
    access_log /var/log/nginx/telegram-gateway-access.log combined;
    error_log /var/log/nginx/telegram-gateway-error.log;

    # Proxy на локальный контейнер
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Обработка WebSocket (если используется)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

#### Шаг 3: Включение конфига и получение сертификата

```bash
# Создание символической ссылки
sudo ln -s /etc/nginx/sites-available/telegram-gateway /etc/nginx/sites-enabled/

# Проверка конфига
sudo nginx -t

# Получение SSL сертификата
sudo certbot certonly --nginx -d your-domain.com

# Перезагрузка Nginx
sudo systemctl restart nginx

# Проверка статуса
sudo systemctl status nginx
```

---

## 🔄 Управление приложением

### Просмотр логов

```bash
# Docker (одиночный контейнер)
docker logs -f telegram-gateway --tail 100

# Docker Compose
docker compose logs -f telegram-gateway --tail 100

# Последние N строк
docker logs --tail 50 telegram-gateway
```

### Перезагрузка контейнера

```bash
# Docker
docker restart telegram-gateway

# Docker Compose
docker compose restart telegram-gateway
```

### Остановка и удаление

```bash
# Docker
docker stop telegram-gateway
docker rm telegram-gateway

# Docker Compose
docker compose down
```

### Обновление приложения

```bash
# Получение свежего кода
git pull origin main

# Пересборка образа
docker build -t telegram-webhook-gateway:latest .

# Docker: остановка старого, запуск нового
docker stop telegram-gateway
docker rm telegram-gateway
docker run -d --name telegram-gateway ... # (команда из Шага 2)

# Docker Compose: проще
docker compose up -d --build
```

---

## ✅ Проверка развертывания

### 1. Проверка статуса приложения

```bash
curl http://localhost:8000/health
# Ответ: {"status":"ok"}
```

### 2. Просмотр статистики

```bash
curl http://localhost:8000/stats
```

### 3. Проверка доступности из интернета

```bash
curl https://your-domain.com/health
```

### 4. Проверка логов контейнера

```bash
docker logs telegram-gateway | tail -100
```

### 5. Проверка диска и памяти

```bash
docker stats telegram-gateway
```

---

## 🚨 Мониторинг и логирование

### Сохранение логов на хост

**В `docker-compose.yml` добавь:**
```yaml
volumes:
  - ./logs:/app/logs
```

**Настройка ротации логов Docker:**
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "5"
```

### Интеграция с systemd (для автозапуска)

**Файл `/etc/systemd/system/telegram-gateway.service`:**
```ini
[Unit]
Description=Telegram Webhook Gateway
After=docker.service
Requires=docker.service

[Service]
Type=simple
Restart=unless-stopped
RestartSec=10

WorkingDirectory=/opt/Telegram-Webhook-Gateway
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

**Включение и запуск:**
```bash
sudo systemctl enable telegram-gateway
sudo systemctl start telegram-gateway
sudo systemctl status telegram-gateway
```

---

## 🔐 Безопасность

### Checklist перед production:

- [ ] `BOT_TOKEN` — приватный, не в git
- [ ] `OUTBOUND_SECRET` — сильный, ≥32 символа
- [ ] `TELEGRAM_SECRET_TOKEN` — установлен (от Telegram)
- [ ] `PUBLIC_MODE=false` или `AUTHORIZED_CHAT_IDS` ограничены
- [ ] SSL сертификат активен (HTTPS)
- [ ] Firewall закрывает все портов кроме 80/443
- [ ] `.env` файл защищен: `chmod 600 .env`
- [ ] Регулярные backaups БД (SQLite)

### Backup БД

```bash
# Ручной backup
cp /opt/Telegram-Webhook-Gateway/data/events.db \
   /backup/events.db.$(date +%Y%m%d_%H%M%S)

# Автоматический backup (cron)
# Добавь в crontab:
0 2 * * * cp /opt/Telegram-Webhook-Gateway/data/events.db /backup/events.db.$(date +\%Y\%m\%d)
```

---

## 🐛 Решение проблем

### Контейнер не стартует

```bash
# Проверь логи
docker logs telegram-gateway

# Проверь синтаксис .env
cat .env | grep -v "^#" | grep -v "^$"

# Проверь порт
lsof -i :8000  # должен быть свободен
```

### SQLite "database is locked"

- Убедись, что только один экземпляр контейнера запущен
- Проверь права доступа на `/app/data`
- Перезагрузи контейнер

### Webhooks не доставляются

1. Проверь логи: `docker logs telegram-gateway`
2. Проверь целевой URL доступен: `curl -v https://your-webhook.com`
3. Проверь firewall не блокирует исходящие соединения
4. Перепроверь синтаксис JSON в `TARGET_WEBHOOK_URLS`

### Высокое использование памяти

```bash
# Проверь утечки памяти
docker stats telegram-gateway

# Перезагрузи контейнер
docker restart telegram-gateway

# Проверь очередь событий
curl http://localhost:8000/stats
```

---

## 📊 Примеры конфигураций

### Пример 1: Несколько целевых вебхуков

```env
BOT_TOKEN=123456:ABC...
OUTBOUND_SECRET=my_secret_32_chars_or_more_xxxx

TARGET_WEBHOOK_URLS=[
  "https://backend1.example.com/telegram",
  "https://backend2.example.com/telegram",
  "https://logging.example.com/events"
]

PUBLIC_MODE=false
AUTHORIZED_CHAT_IDS=123456789,987654321
```

### Пример 2: Приватный бот с авторизацией

```env
BOT_TOKEN=123456:ABC...
TELEGRAM_SECRET_TOKEN=secret_from_telegram_setwebhook
TARGET_WEBHOOK_URL=https://private.example.com/webhook

PUBLIC_MODE=false
AUTHORIZED_CHAT_IDS=111222333,444555666

RATE_LIMIT_PER_MIN=10
MAX_RETRIES=3
```

### Пример 3: Мультибот конфиг

```env
BOT_TOKEN=first_bot_token  # Основной бот
BOT_CONTEXT_BY_KEY={
  "key1": "111222333444",
  "key2": "555666777888"
}

TELEGRAM_WEBHOOK_PATH=/telegram/webhook/{bot_key}

TARGET_WEBHOOK_URL=https://api.example.com/events

PASSWORD=secure_password
```

---

## 📞 Дополнительные ресурсы

- [FastAPI документация](https://fastapi.tiangolo.com/)
- [Docker документация](https://docs.docker.com/)
- [Docker Compose справка](https://docs.docker.com/compose/)
- [Telegram Bot API](https://core.telegram.org/bots/api)

---

**Последнее обновление:** March 2026
