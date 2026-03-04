# 🏆 Production Best Practices & Security Guide

Рекомендации по безопасному развертыванию в production окружении.

---

## 🔐 Секретность и защита данных

### ✅ Переменные окружения и секреты

**Правильно:**
```bash
# Использовать .env файл (НЕ в git)
echo ".env" >> .gitignore

# Установить строгие права доступа
chmod 600 .env
chmod 600 .env.example  # если содержит примеры

# Использовать переменные окружения
export BOT_TOKEN="..."
export OUTBOUND_SECRET="..."

# Или через secrets manager (Docker Secrets, HashiCorp Vault)
docker secret create bot_token .env
```

**Неправильно:**
```bash
# ❌ Хардкодировать секреты в коде
BOT_TOKEN="123456:ABC..." # в .py файлах

# ❌ Коммитить .env в git
git add .env && git commit

# ❌ Публиковать секреты в логах
print(f"BOT_TOKEN={BOT_TOKEN}")  # видимо в доках, скринах
```

### ✅ Генерация сильных секретов

```python
# Правильно
import secrets
token = secrets.token_hex(32)  # 64 символа, криптографически стойко
print(token)  # c7f9e8d2a1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7

# ИЛИ
import os
token = os.urandom(32).hex()

# ИЛИ через bash
openssl rand -hex 32
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### ✅ Вращение секретов

```bash
# Регулярно обновляй OUTBOUND_SECRET (ежеквартально)
# Дай бекендам время на обновление
# Сохрани старые версии в отдельный список

# Например в Dockerfile:
ENV OUTBOUND_SECRETS_LIST="current_secret,backup_secret_1,backup_secret_2"
# Приложение проверяет все три при верификации
```

---

## 🔒 Сетевая безопасность

### ✅ Firewall конфигурация

```bash
# Разрешить только необходимые порты
sudo ufw default deny incoming
sudo ufw default allow outgoing

# HTTP/HTTPS (для вебхуков)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# SSH (для управления)
sudo ufw allow 22/tcp        # или другой custom port
sudo ufw allow from 192.168.1.0/24 to any port 22  # ограничить IP

# Docker недоступен снаружи (8000 только локально)
# Nginx слушает 80/443 и проксирует на 8000

sudo ufw enable
sudo ufw status
```

### ✅ Reverse proxy (Nginx)

```nginx
# /etc/nginx/sites-available/telegram-gateway

# 1. Перенаправление HTTP → HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

# 2. HTTPS с защитой
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL сертификаты (из Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Безопасные SSL параметры
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5:!3DES;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Безопасности заголовки
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer" always;

    # Rate limiting на уровне Nginx
    limit_req_zone $binary_remote_addr zone=telegram:10m rate=100r/m;
    limit_req zone=telegram burst=20 nodelay;

    # Логирование
    access_log /var/log/nginx/telegram-gateway.access.log combined;
    error_log /var/log/nginx/telegram-gateway.error.log;

    # Proxy к Docker контейнеру
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        
        # Таймауты
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        # Buffers
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
        proxy_busy_buffers_size 8k;
    }

    # Запретить доступ к чувствительным файлам
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    location ~ ~$ {
        deny all;
        access_log off;
        log_not_found off;
    }
}
```

### ✅ SSL сертификаты

```bash
# Установить Certbot
sudo apt install -y certbot python3-certbot-nginx

# Получить сертификат (автоматическое обновление)
sudo certbot certonly --nginx -d your-domain.com

# Проверить автообновление
sudo systemctl status certbot.timer
sudo certbot renew --dry-run  # Test renewal

# Сертификаты хранятся в:
# /etc/letsencrypt/live/your-domain.com/
```

---

## 🛡️ Доступ и аутентификация

### ✅ Ограничение доступа к статус-эндпоинтам

```python
# В приложении добавить аутентификацию для /stats

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthCredentials

security = HTTPBearer()

async def verify_api_key(credentials: HTTPAuthCredentials = Depends(security)):
    if credentials.credentials != settings.ADMIN_API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return credentials.credentials

@app.get("/stats")
async def stats(auth: str = Depends(verify_api_key)):
    # Only if correct API token provided
    return {...}
```

### ✅ Ограничение доступа к контейнеру

```bash
# Docker: не выставлять порт наружу
# ❌ НЕПРАВИЛЬНО:
docker run -p 8000:8000 ...  # Доступен из интернета

# ✅ ПРАВИЛЬНО:
docker run -p 127.0.0.1:8000:8000 ...  # Только локально
# Или не выставлять вообще, Nginx проксирует
```

### ✅ SSH ключи вместо паролей

```bash
# Запретить root login и пароли
sudo nano /etc/ssh/sshd_config

# Добавить/изменить:
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

---

## 📊 Мониторинг и логирование

### ✅ Централизованное логирование

```yaml
# docker-compose.yml
logging:
  driver: "splunk"  # или syslog, fluentd, etc
  options:
    splunk-token: ${SPLUNK_TOKEN}
    splunk-url: https://splunk.example.com:8088
    splunk-source: telegram-gateway
    splunk-sourcetype: docker
```

### ✅ Мониторинг здоровья приложения

```bash
# Регулярные health checks
curl -f https://your-domain.com/health || alert

# Через systemd timer
sudo nano /etc/systemd/system/telegram-health-check.timer

[Unit]
Description=Telegram Gateway Health Check
Requires=telegram-health-check.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

### ✅ Prometheus метрики (опционально)

```python
# Добавить в приложение Prometheus поддержку
from prometheus_client import Counter, Histogram, generate_latest

webhook_events = Counter('telegram_webhook_events_total', 'Total webhook events')
webhook_latency = Histogram('telegram_webhook_latency_seconds', 'Webhook latency')
queue_size = Gauge('telegram_queue_size', 'Queue size')

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# Скрейпить из Prometheus:
# scrape_configs:
#   - job_name: 'telegram-gateway'
#     static_configs:
#       - targets: ['localhost:8000']
#       - targets: ['your-domain.com:443/metrics']
```

---

## 💾 Backup и восстановление

### ✅ Автоматический backup

```bash
# Crontab для ежедневного backup
0 2 * * * /usr/local/bin/terraform-backup.sh

# /usr/local/bin/telegram-backup.sh
#!/bin/bash
set -e

BACKUP_DIR="/backups/telegram"
DB_PATH="/opt/Telegram-Webhook-Gateway/data/events.db"
RETENTION_DAYS=30

# Создать backup
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/events.db.$(date +%Y%m%d_%H%M%S).backup"
cp "$DB_PATH" "$BACKUP_FILE"
gzip "$BACKUP_FILE"

# Удалить старые backups
find "$BACKUP_DIR" -name "*.backup.gz" -mtime +$RETENTION_DAYS -delete

# Отправить на удаленный сервер (опционально)
# scp "$BACKUP_FILE.gz" backup@remote:/backups/
```

### ✅ Резервное хранилище

```bash
# S3 backup
aws s3 sync /backups/telegram s3://my-telegram-backups/ --delete

# GoogleDrive backup
rclone copy /backups/telegram gdrive:/telegram-backups/ --delete-after

# Rsync на другой сервер
rsync -avz /backups/telegram backup@secondary-server:/backups/
```

---

## 🔄 Обновления и patch management

### ✅ План обновления

```bash
# 1. Сделать backup
cp data/events.db data/events.db.pre-update

# 2. Остановить приложение
docker compose down

# 3. Обновить код
git fetch origin
git checkout v1.2.3  # или main

# 4. Пересобрать образ
docker compose build --no-cache

# 5. Запустить (тесты начнут запускаться)
docker compose up -d
docker compose logs -f

# 6. Проверить здоровье
curl https://your-domain.com/health

# 7. Откатить если нужно
git checkout HEAD~1
docker compose build --no-cache
docker compose restart
```

### ✅ Безопасные обновления зависимостей

```bash
# Регулярно проверять обновления
pip list --outdated

# Безопасно обновлять
pip install --upgrade fastapi httpx
# Тестировать в staging перед production

# Использовать pin версий в requirements.txt
# fastapi==0.133.0  # вместо fastapi>=0.100.0
```

---

## 🚨 Incident response

### ✅ План действий при инциденте

```markdown
## Если контейнер упал:
1. Проверить логи: `docker logs telegram-gateway | tail -100`
2. Перезапустить: `docker restart telegram-gateway`
3. Если не помогло, откатить на последний known good:
   - git checkout HEAD~1
   - docker compose down && docker compose up -d
4. Исключить из балансировки, исследовать проблему

## Если высокое использование памяти:
1. Проверить размер БД: `du -h data/events.db`
2. Очистить старые события
3. Перезагрузить контейнер
4. Добавить swap памяти

## Если не доставляются вебхуки:
1. Проверить целевой URL доступен
2. Проверить firewall
3. Проверить OUTBOUND_SECRET совпадает
4. Проверить target webhook не отклоняет запросы
5. Смотреть retry логи
```

---

## 📋 Security Checklist

Перед production deployment заполни checklist:

- [ ] **Секреты:**
  - [ ] `BOT_TOKEN` - никогда не в git, только в secrets
  - [ ] `OUTBOUND_SECRET` - минимум 32 символа, криптографически стойко
  - [ ] `TELEGRAM_SECRET_TOKEN` - установлен в Telegram
  - [ ] `.env` защищен: `chmod 600`

- [ ] **Сеть:**
  - [ ] SSL/TLS включен (HTTPS)
  - [ ] Сертификат валиден и не expired
  - [ ] Firewall настроен (только 80/443 наружу)
  - [ ] Docker порт не открыт наружу
  - [ ] Nginx reverse proxy работает

- [ ] **Доступ:**
  - [ ] SSH ключи вместо паролей
  - [ ] Root login запрещен
  - [ ] Пароли для управления базой защищены
  - [ ] API ключи для /stats/pull endpoints установлены

- [ ] **Мониторинг:**
  - [ ] Health checks настроены
  - [ ] Логирование включено и централизовано
  - [ ] Алерты на сбой приложения
  - [ ] Мониторинг ресурсов (CPU, память, диск)

- [ ] **Резервное копирование:**
  - [ ] Автоматический backup SQLite ежедневно
  - [ ] Бэкапы хранятся на другом сервере
  - [ ] Проверена процедура восстановления
  - [ ] Retention policy установлена (30+ дней)

- [ ] **Обновления:**
  - [ ] План обновления документирован
  - [ ] Есть процедура отката
  - [ ] Staging/prod окружения отделены
  - [ ] Зависимости регулярно обновляются (уязвимости)

- [ ] **Документация:**
  - [ ] Инструкции развертывания актуальны
  - [ ] План disaster recovery описан
  - [ ] Контакты на-случай-чрезвычайных-ситуаций указаны
  - [ ] Access от других админов задокументирован

---

## 📞 Дополнительные материалы

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Docker Security Best Practices](https://docker.com/blog/docker-security-best-practices/)
- [Nginx Security Hardening](https://nginx.org/en/docs/http/ngx_http_ssl_module.html)
- [CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks)

---

**Secure deployment 🔐** - это процесс, а не конечный пункт!
