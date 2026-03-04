# 🎯 Cheat Sheet - часто используемые команды

Быстрый справочник команд для управления приложением в Docker.

---

## 🚀 Первый запуск

```bash
# 1. Клонировать репозиторий
git clone https://github.com/you/Telegram-Webhook-Gateway.git
cd Telegram-Webhook-Gateway

# 2. Создать .env файл
cp .env.example .env
nano .env  # Отредактировать BOT_TOKEN и другие параметры

# 3. Запустить через Docker Compose
docker compose up -d

# 4. Проверить статус
docker compose ps
curl http://localhost:8000/health
```

---

## 🏗️ Построение и запуск

### Docker Compose (рекомендуется)
```bash
# Сборка образа
docker compose build

# Запуск в фоне
docker compose up -d

# Запуск с просмотром логов
docker compose up

# Остановка
docker compose down

# Полная очистка (с томами)
docker compose down -v

# Пересборка и перезагрузка
docker compose up -d --build
```

### Docker вручную
```bash
# Сборка образа
docker build -t telegram-gateway:latest .

# Запуск
docker run -d \
  --name telegram-gateway \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  telegram-gateway:latest

# Остановка
docker stop telegram-gateway

# Запуск снова
docker start telegram-gateway

# Удаление
docker rm telegram-gateway
```

---

## 📊 Мониторинг и логи

```bash
# Просмотр логов в реальном времени (последние 100 строк)
docker compose logs -f --tail 100

# Просмотр последних N строк (без follow)
docker compose logs --tail 50

# Все логи (много!)
docker compose logs

# Логи одного контейнера
docker logs -f telegram-gateway

# Статистика контейнера (CPU, память)
docker stats telegram-gateway

# Список запущенных контейнеров
docker ps
docker ps -a  # включая остановленные
```

---

## 🔍 Проверка здоровья

```bash
# Проверить статус приложения
curl http://localhost:8000/health
# Результат: {"status":"ok"}

# Получить статистику очереди
curl http://localhost:8000/stats

# Более подробный вывод
curl -s http://localhost:8000/stats | python3 -m json.tool

# Проверить доступ по HTTPS (после настройки Nginx)
curl https://your-domain.com/health
```

---

## 🔧 Управление контейнером

```bash
# Перезагрузить приложение
docker compose restart
docker restart telegram-gateway

# Запустить shell внутри контейнера
docker compose exec telegram-gateway bash
docker exec -it telegram-gateway bash

# Выполнить команду в контейнере
docker compose exec telegram-gateway curl http://localhost:8000/health
docker exec telegram-gateway ls -la /app/data

# Скопировать файл из контейнера
docker cp telegram-gateway:/app/data/events.db ./events.db.backup

# Скопировать файл в контейнер
docker cp ./my-file.txt telegram-gateway:/app/my-file.txt
```

---

## 💾 Работа с БД (SQLite)

```bash
# Размер база данных
ls -lh ./data/events.db
du -sh ./data/

# Сделать резервную копию
cp ./data/events.db ./data/events.db.backup

# Или через Docker
docker exec telegram-gateway cp /app/data/events.db /app/data/events.db.backup

# Просмотр БД (если установлен sqlite3 на хосте)
sqlite3 ./data/events.db ".tables"
sqlite3 ./data/events.db "SELECT COUNT(*) FROM events;"

# Удалить базу (⚠️ ОПАСНО)
rm ./data/events.db
docker compose restart  # Создаст новую пустую БД
```

---

## 🔐 Генерация секретов

```bash
# Сгенерировать безопасный токен (32 байта = 64 символа)
python3 -c "import secrets; print(secrets.token_hex(32))"

# Или через OpenSSL
openssl rand -hex 32

# Или через dd
dd if=/dev/urandom bs=1 count=32 2>/dev/null | xxd -p

# Проверить что число достаточно случайно
python3 << 'EOF'
import secrets
for i in range(5):
    print(secrets.token_hex(32))
EOF
```

---

## 🔄 Обновление приложения

```bash
# Получить свежий код
git pull origin main

# Сделать backup перед обновлением
cp ./data/events.db ./data/events.db.pre-update

# Пересобрать образ и перезагрузить
docker compose up -d --build

# Проверить что всё работает
docker compose logs --tail 50
curl http://localhost:8000/health

# Если что-то сломалось - откатиться
git checkout HEAD~1
docker compose up -d --build
```

---

## 🌐 Настройка Nginx

```bash
# Проверить синтаксис конфига
sudo nginx -t

# Перезагрузить конфиг (без перезагрузки)
sudo systemctl reload nginx

# Полная перезагрузка
sudo systemctl restart nginx

# Статус
sudo systemctl status nginx

# Логи Nginx
tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/access.log
```

---

## 🔓 SSL / Let's Encrypt

```bash
# Получить сертификат
sudo certbot certonly --nginx -d your-domain.com

# Обновить сертификат вручную
sudo certbot renew

# Проверить статус сертификата
sudo certbot certificates

# Тест автообновления
sudo certbot renew --dry-run

# Логи Certbot
sudo systemctl status certbot.timer
journalctl -u certbot.timer -n 50
```

---

## 🔧 Docker Compose специально

```bash
# Полная информация о проекте
docker compose config

# Список сервисов и их статус
docker compose ps

# Просмотр конфига переменных
docker compose config | grep -A 20 "environment"

# Запуск в интерактивном режиме (Ctrl+C для выхода)
docker compose up

# Запуск с пересборкой (даже если образ не изменился)
docker compose up --build --force-recreate

# Очистить неиспользуемые ресурсы
docker compose down --remove-orphans

# Scale сервис (если нужны реплики)
docker compose up -d --scale telegram-gateway=2
```

---

## 🚨 Решение проблем

```bash
# Проверить что процесс слушает на порту
lsof -i :8000
netstat -tlnp | grep 8000

# Если порт занят - найти кто занимает
ps aux | grep $(lsof -ti :8000)

# Освободить порт (осторожно!)
kill -9 $(lsof -ti :8000)

# Проверить память
free -h
docker stats

# Проверить диск
df -h
du -sh ./data/

# Проверить сетевое соединение
ping -c 3 8.8.8.8
curl -v https://api.telegram.org

# Посмотреть network подключение контейнера
docker inspect telegram-gateway | grep IPAddress
```

---

## 📝 Файловая система

```bash
# Создать/отредактировать .env
nano .env
# или
vi .env
# или
cat > .env << 'EOF'
BOT_TOKEN=your_token
TARGET_WEBHOOK_URL=https://example.com
EOF

# Права доступа на .env (очень важно!)
chmod 600 .env
ls -la .env  # Должен быть "rw-------"

# Создать директории если не существуют
mkdir -p ./data ./logs ./backups

# Смотреть структуру проекта
tree -L 2 -I '__pycache__|*.pyc'
# или через ls
ls -laR | head -50
```

---

## 🖥️ Systemd (автозагрузка)

```bash
# Посмотреть существующий service
sudo systemctl cat telegram-gateway.service

# Перезагрузить systemd конфиги
sudo systemctl daemon-reload

# Включить автозагрузку
sudo systemctl enable telegram-gateway.service

# Запустить
sudo systemctl start telegram-gateway

# Остановить
sudo systemctl stop telegram-gateway

# Статус
sudo systemctl status telegram-gateway

# Просмотр логов
sudo journalctl -u telegram-gateway -n 100 -f

# Полная очистка
sudo systemctl stop telegram-gateway
sudo systemctl disable telegram-gateway
```

---

## 📊 Benchmark и performance

```bash
# Нагрузочное тестирование (требует ab или siege)
ab -n 1000 -c 10 http://localhost:8000/health

# Или с curl
for i in {1..100}; do curl -s http://localhost:8000/health > /dev/null & done; wait

# Профилирование памяти (если приложение медленнит)
docker exec telegram-gateway python3 -m memory_profiler script.py

# Проверить скорость отклика
time curl http://localhost:8000/health
```

---

## 🔐 Безопасность шпаргалка

```bash
# Установить права на .env
chmod 600 .env

# Проверить что BOT_TOKEN не в коде
grep -r "BOT_TOKEN=" --include="*.py" .
grep -r "^BOT_TOKEN" --include="*.py" .

# Убедиться что .env не в git
git ls-files | grep .env  # Не должно быть .env

# Проверить что Docker контейнер не выставляет внутренний порт
docker inspect telegram-gateway | grep PortBindings
# Должен быть только (или локально)
```

---

## 🐛 Внутренний информирующий

```bash
# Список всех документов по развертыванию
ls -1 *.md DEPLOYMENT* PRODUCTION* QUICKSTART* EXAMPLES*

# Проверить что docker-helper.sh исполняемый
ls -l docker-helper.sh

# Выполнить команду из docker-helper
chmod +x docker-helper.sh
./docker-helper.sh help
./docker-helper.sh status
```

---

## 🎯 Быстрые сценарии

### Полный "свежий старт"
```bash
# Если всё испорчено - начни заново
docker compose down -v  # Удалить всё
rm -rf ./data           # Удалить данные
docker system prune -a  # Почистить Docker
docker compose up -d --build  # Собрать заново
```

### Хеалти чек за 10 сек
```bash
docker compose ps && curl http://localhost:8000/health && echo "✓ OK"
```

### Быстрый backup
```bash
mkdir -p ./backups
cp ./data/events.db ./backups/events.db.$(date +%Y%m%d_%H%M%S)
echo "Backup done in ./backups/"
```

### Просмотр последних ошибок
```bash
docker compose logs --tail 50 | grep -E "ERROR|Exception|Failed|error"
```

### Проверка что всё работает
```bash
echo "1. Docker статус:" && docker compose ps && \
echo -e "\n2. Health check:" && curl http://localhost:8000/health && \
echo -e "\n3. Stats:" && curl -s http://localhost:8000/stats | python3 -m json.tool && \
echo -e "\n✅ All OK!"
```

---

## 💾 Backup & Restore за 1 команду

```bash
# Backup
tar czf backup_$(date +%Y%m%d_%H%M%S).tar.gz ./data ./logs .env docker-compose.yml

# Restore (в новой директории)
tar xzf backup_20240101_120000.tar.gz
docker compose up -d
```

---

**Спасибо за использование! 🚀** 

Для полной информации смотри [DOCS_INDEX.md](DOCS_INDEX.md)
