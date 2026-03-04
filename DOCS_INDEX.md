# 📚 Индекс документации развертывания

Полный навигатор по инструкциям по развертыванию Telegram Webhook Gateway в Docker.

---

## 🚀 Быстрые ссылки по уровню опыта

### 👨‍💻 Для новичков
1. **[QUICKSTART.md](QUICKSTART.md)** - Начни отсюда! ⚡
   - 5 шагов за 5 минут
   - Базовая конфигурация
   - Проверка что работает

2. **[Примеры конфигураций](EXAMPLES.md#️⃣-простой-сценарий-один-бот-один-webhook)**
   - Простой сценарий: 1 бот → 1 webhook
   - Копируй и адаптируй

### 🔧 Для опытных разработчиков
1. **[DEPLOYMENT.md](DEPLOYMENT.md)** - Полное руководство
   - Все сценарии развертывания
   - Docker Compose, Nginx, SSL
   - Systemd, мониторинг, backup

2. **[PRODUCTION.md](PRODUCTION.md)** - Production best practices
   - Безопасность и сетевые настройки
   - Мониторинг и логирование
   - Incident response план

3. **[EXAMPLES.md](EXAMPLES.md)** - 8+ примеров конфиг
   - Многобекенд конфиг
   - Приватный бот
   - Мультибот
   - Enterprise setup

---

## 📋 Полный список документации

### Основные файлы

| Файл | Описание | Для кого |
|------|---------|---------|
| [QUICKSTART.md](QUICKSTART.md) | За 5 шагов в production | Новички |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Полное руководство (15+ разделов) | Все |
| [EXAMPLES.md](EXAMPLES.md) | 8 готовых конфигураций | Разработчики |
| [PRODUCTION.md](PRODUCTION.md) | Security & Best Practices | DevOps/Security |
| [.env.example](.env.example) | Шаблон переменных окружения | Все |
| [docker-compose.yml](docker-compose.yml) | Docker Compose конфиг | Все |
| [Dockerfile](Dockerfile) | Образ контейнера | DevOps |
| [docker-helper.sh](docker-helper.sh) | Вспомогательные скрипты | Все |

---

## 🎯 По задачам

### Я хочу...

#### 🟢 **Быстро стартовать локально**
👉 [QUICKSTART.md - шаг 1-4](QUICKSTART.md#️⃣-за-5-шагов)
```bash
cp .env.example .env  # Отредактировать
docker compose up -d
curl http://localhost:8000/health
```

#### 🟢 **Развернуть на сервере**
👉 [DEPLOYMENT.md - вариант 1 или 2](DEPLOYMENT.md#-развертывание-с-docker)
```bash
git clone & docker build & docker run
# или
docker compose up -d
```

#### 🟡 **Настроить Production правильно**
👉 [PRODUCTION.md](PRODUCTION.md) + [EXAMPLES.md](EXAMPLES.md#️⃣-максимальный-enterprise)

#### 🟡 **Добавить SSL (HTTPS)**
👉 [DEPLOYMENT.md - Nginx + SSL](DEPLOYMENT.md#️⃣-настройка-nginx-как-reverse-proxy)

#### 🟡 **Несколько вебхуков (fan-out)**
👉 [EXAMPLES.md - сценарий 2](EXAMPLES.md#️⃣-надежный-сценарий-мультибекенд-с-подписью)

#### 🔴 **Запустить несколько ботов на одном сервере**
👉 [EXAMPLES.md - сценарий 4](EXAMPLES.md#️⃣-мультибот-несколько-независимых-ботов-на-одном-сервере)

#### 🔴 **Решить проблему / дебаг**
👉 [DEPLOYMENT.md - Решение проблем](DEPLOYMENT.md#-решение-проблем)

#### 🔴 **Сделать backup и восстановление**
👉 [PRODUCTION.md - Backup и восстановление](PRODUCTION.md#-backup-и-восстановление)

#### 🔴 **Обновить приложение safely**
👉 [DEPLOYMENT.md - обновление](DEPLOYMENT.md#обновление-приложения) + [PRODUCTION.md - обновления](PRODUCTION.md#-обновления-и-patch-management)

---

## 🏗️ Архитектура в одном файле

```
                    Internet (HTTPS)
                            ↓
                    ┌─────────────────┐
                    │   Nginx (SSL)   │ :443
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │ Docker Container│
                    │   FastAPI App   │ :8000
                    │  • Webhook RX   │
                    │  • SQLite Queue │
                    │  • Worker Loop  │
                    │  • Health Check │
                    └────────┬────────┘
                             ↓
                  [Telegram Server] ← 📞 Bots

Target Webhooks (Fan-out):
    ├─ Backend 1
    ├─ Backend 2
    ├─ Backend 3
    └─ Logging Service
```

---

## 🔐 Безопасность шпаргалка

```bash
# Сгенерировать безопасный токен
python3 -c "import secrets; print(secrets.token_hex(32))"

# Защитить .env файл
chmod 600 .env

# Проверить что контейнер работает
docker exec telegram-gateway curl http://localhost:8000/health

# Проверить логи на ошибки
docker logs -f telegram-gateway --tail 50

# Сделать backup БД
docker exec telegram-gateway cp /app/data/events.db /app/data/events.db.backup
```

---

## 📦 Для разных платформ

### Локальная машина (Mac/Linux)
1. [QUICKSTART.md](QUICKSTART.md) ✅
2. `docker-helper.sh setup && docker-helper.sh start`
3. Готово!

### Debian/Ubuntu сервер
1. [QUICKSTART.md](QUICKSTART.md) ✅
2. [DEPLOYMENT.md - Docker Compose](DEPLOYMENT.md#️⃣-docker-compose-рекомендуется-для-production) ✅
3. [DEPLOYMENT.md - Nginx SSL](DEPLOYMENT.md#️⃣-настройка-nginx-как-reverse-proxy) ✅
4. [DEPLOYMENT.md - Systemd](DEPLOYMENT.md#интеграция-с-systemd-для-автозапуска) ✅
5. [PRODUCTION.md](PRODUCTION.md) ✅

### Railway / Fly.io / Render
1. [EXAMPLES.md - сценарий 5](EXAMPLES.md#️⃣-production-на-railwayapp)
2. Подключи твой repo
3. Задай secrets (BOT_TOKEN, OUTBOUND_SECRET)
4. Deploy! 🚀

### Docker Swarm / Kubernetes
1. [EXAMPLES.md - сценарий 6](EXAMPLES.md#️⃣-docker-swarm--kubernetes-ready)
2. [DEPLOYMENT.md - Docker Compose](DEPLOYMENT.md#️⃣-docker-compose-рекомендуется-для-production)
3. Адаптируй для твоей orchestration

---

## 🆘 Помощь и troubleshooting

### Частые проблемы

| Проблема | Решение |
|----------|---------|
| Контейнер не стартует | [DEPLOYMENT.md - Контейнер не стартует](DEPLOYMENT.md#контейнер-не-стартует) |
| "database is locked" | [DEPLOYMENT.md - database is locked](DEPLOYMENT.md#sqlite-database-is-locked) |
| Webhooks не доставляются | [DEPLOYMENT.md - Webhooks не доставляются](DEPLOYMENT.md#webhooks-не-доставляются) |
| Высокое использование памяти | [DEPLOYMENT.md - Память](DEPLOYMENT.md#высокое-использование-памяти) |

### Команды для дебага

```bash
# Посмотреть логи
docker logs -f telegram-gateway

# Проверить статус контейнера
docker ps | grep telegram

# Открыть shell в контейнере
docker exec -it telegram-gateway /bin/bash

# Проверить что приложение живо
curl http://localhost:8000/health
curl http://localhost:8000/stats

# Посмотреть использование ресурсов
docker stats telegram-gateway
```

---

## 🔄 Workflow обновления

```
1. Заполни PRODUCTION.md Checklist
            ↓
2. Выбери сценарий из EXAMPLES.md
            ↓
3. Следуй QUICKSTART.md для basic setup
            ↓
4. Настрой Nginx/SSL из DEPLOYMENT.md
            ↓
5. Примени Security рекомендации из PRODUCTION.md
            ↓
6. Настрой мониторинг и backup
            ↓
7. ✅ Production Ready!
```

---

## 💡 Про переменные окружения

**Полный список в:** [.env.example](.env.example) (60+ строк с комментариями)

**Быстрые примеры:**
- [Одна цель](EXAMPLES.md#️⃣-простой-сценарий-один-бот-один-webhook)
- [Несколько целей](EXAMPLES.md#️⃣-надежный-сценарий-мультибекенд-с-подписью)
- [Enterprise](EXAMPLES.md#️⃣-максимальный-enterprise)

---

## 🎓 Рекомендуемый порядок чтения

Для полного понимания проекта:

1. **README.md** (в корне проекта) - Overview
2. **QUICKSTART.md** (этот файл) - Практика за 5 минут
3. **EXAMPLES.md** - Узнай что возможно
4. **DEPLOYMENT.md** - Все детали
5. **PRODUCTION.md** - Готовься к production

**Или прыгай прямо в QUICKSTART.md если спешишь!** ⚡

---

## 📞 Дополнительные ссылки

- [GitHub репо](https://github.com/) - Issues, discussoins
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [FastAPI документация](https://fastapi.tiangolo.com/)
- [Docker документация](https://docs.docker.com/)

---

**Выбери раздел выше и начни! 🚀**
