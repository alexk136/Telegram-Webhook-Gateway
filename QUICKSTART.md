# ⚡ Быстрый старт (Quick Start)

Minimal инструкция для развертывания на сервере за 5 минут.

## 🚀 За 5 шагов

### 1️⃣ Клонирование и подготовка

```bash
cd /opt
git clone https://github.com/you/Telegram-Webhook-Gateway.git
cd Telegram-Webhook-Gateway
cp .env.example .env
chmod 600 .env
chmod +x docker-helper.sh  # Если есть скрипт
```

### 2️⃣ Конфигурация (отредактировать `.env`)

Отредактируй основные параметры в файле `.env`:

```env
# ⭐ ОБЯЗАТЕЛЬНО
BOT_TOKEN=YOUR_BOT_TOKEN_HERE
TARGET_WEBHOOK_URL=https://your-backend.com/telegram

# 🔐 РЕКОМЕНДУЕТСЯ
OUTBOUND_SECRET=your_secret_key_generated_here
TELEGRAM_SECRET_TOKEN=your_telegram_secret_token

# 🔒 ДОПОЛНИТЕЛЬНО (если приватный бот)
PUBLIC_MODE=false
AUTHORIZED_CHAT_IDS=123456789
```

**Как получить значения:**
- `BOT_TOKEN` → напиши @BotFather в Telegram
- `OUTBOUND_SECRET` → `python3 -c "import secrets; print(secrets.token_hex(32))"`
- `TARGET_WEBHOOK_URL` → URL твоего backend сервера

### 3️⃣ Запуск контейнера

```bash
# Вариант A: С помощью скрипта (если есть)
./docker-helper.sh setup
./docker-helper.sh start

# Вариант B: Вручную через Docker Compose
docker compose up -d

# Вариант C: Вручную через Docker
docker build -t telegram-gateway:latest .
docker run -d \
  --name telegram-gateway \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  telegram-gateway:latest
```

### 4️⃣ Проверка статуса

```bash
# Проверь, что контейнер работает
docker ps | grep telegram

# Проверь логи
docker logs -f telegram-gateway

# Проверь здоровье приложения
curl http://localhost:8000/health
# Должен вернуть: {"status":"ok"}
```

### 5️⃣ Настройка Telegram webhook

```bash
# Установи webhook в Telegram (замени на реальный URL)
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://your-domain.com/telegram/webhook"

# Проверь что webhook установлен
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

---

## 🎯 Что дальше?

### Доступные endpoints:

```
GET  /health          → Проверка здоровья
GET  /stats           → Статистика очереди
POST /telegram/webhook → Входящие события от Telegram
```

### Проверка работы:

```bash
# Отправь сообщение боту в Telegram, затем:
curl http://localhost:8000/stats

# Должна появиться статистика об обработанных событиях
```

### Мониторинг логов:

```bash
# Смотреть логи в реальном времени
docker logs -f telegram-gateway --tail 100

# Или через скрипт
./docker-helper.sh logs
```

---

## 🔧 Управление контейнером

```bash
# Перезагрузить приложение
docker restart telegram-gateway

# Остановить
docker stop telegram-gateway

# Запустить снова
docker start telegram-gateway

# Удалить (полная очистка)
docker rm -f telegram-gateway
# затем пересоздать:
docker run -d ... (команда выше)
```

---

## 📦 Backup БД

```bash
# Сделать backup
cp ./data/events.db ./data/events.db.backup

# Или через скрипт
./docker-helper.sh backup
```

---

## 🐛 Частые проблемы

### ❌ "Connection refused" на `curl http://localhost:8000/health`

- Контейнер не запустился: `docker ps` (должен быть в списке)
- Проверь логи: `docker logs telegram-gateway`
- Проверь `BOT_TOKEN` в `.env`

### ❌ "Port 8000 already in use"

```bash
# Найди что занимает порт
lsof -i :8000

# Или используй другой порт
docker run -d -p 8080:8000 ...  # теперь будет доступен на :8080
```

### ❌ "Webhooks не доставляются"

1. Проверь логи: какие ошибки?
2. Проверь доступность целевого URL: `curl -v https://your-backend.com/webhook`
3. Убедись что TARGET_WEBHOOK_URL в `.env` верный
4. Проверь firewall не блокирует исходящие соединения

### ❌ "database is locked"

- Перезагрузи контейнер: `docker restart telegram-gateway`
- Убедись что только один контейнер запущен: `docker ps`

---

## 🌐 Для production (с Nginx + SSL)

### 1. Установи Nginx и Certbot

```bash
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
```

### 2. Создай конфиг Nginx

Файл: `/etc/nginx/sites-available/telegram`

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. Получи SSL сертификат

```bash
sudo certbot certonly --nginx -d your-domain.com
```

### 4. Включи конфиг

```bash
sudo ln -s /etc/nginx/sites-available/telegram /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 5. Установи webhook в Telegram

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://your-domain.com/telegram/webhook"
```

---

## 📋 Чеклист перед production

- [ ] `BOT_TOKEN` установлен и верный
- [ ] `TARGET_WEBHOOK_URL` указан
- [ ] `OUTBOUND_SECRET` установлен (сильный пароль)
- [ ] SSL сертификат активен (HTTPS)
- [ ] Firewall открыт для портов 80/443
- [ ] Webhook установлен в Telegram
- [ ] Протестировано: отправь боту сообщение и проверь логи
- [ ] Backup BD сделан
- [ ] Мониторинг настроен (опционально)

---

## 📞 Дополнительные ресурсы

- [Полное руководство развертывания](DEPLOYMENT.md)
- [Docker документация](https://docs.docker.com/)
- [Telegram Bot API](https://core.telegram.org/bots/api)

---

**Готово! 🎉** Приложение работает и принимает события от Telegram.
