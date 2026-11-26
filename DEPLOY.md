# Развертывание проекта СМЕНА на Timeweb VPS

## Требования

- VPS с Ubuntu 20.04 или выше
- Root доступ к серверу
- Доменное имя (опционально, но рекомендуется)

## 1. Подготовка сервера

### Подключение к серверу

```bash
ssh root@your_server_ip
```

### Обновление системы

```bash
apt update && apt upgrade -y
```

### Установка необходимых пакетов

```bash
# Python и зависимости
apt install -y python3.10 python3-pip python3-venv python3-dev

# PostgreSQL
apt install -y postgresql postgresql-contrib

# Nginx
apt install -y nginx

# Git
apt install -y git

# Дополнительные инструменты
apt install -y build-essential libpq-dev
```

## 2. Настройка PostgreSQL

### Создание базы данных и пользователя

```bash
# Переключение на пользователя postgres
sudo -u postgres psql

# В psql выполните:
CREATE DATABASE smena_db;
CREATE USER smena_user WITH PASSWORD 'strong_password_here';
GRANT ALL PRIVILEGES ON DATABASE smena_db TO smena_user;
\q
```

## 3. Настройка проекта

### Создание пользователя для приложения

```bash
adduser --disabled-password --gecos "" smena
```

### Клонирование проекта

```bash
cd /home/smena
git clone <your_repository_url> app
cd app
chown -R smena:smena /home/smena/app
```

### Создание виртуального окружения

```bash
su - smena
cd app
python3 -m venv venv
source venv/bin/activate
```

### Установка зависимостей

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn
```

### Настройка переменных окружения

```bash
nano .env
```

Заполните файл:

```env
# Telegram Bot
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_IDS=your_telegram_id

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=smena_db
DB_USER=smena_user
DB_PASSWORD=strong_password_here

# Admin Panel
ADMIN_SECRET_KEY=generate_random_secret_key_here
ADMIN_HOST=0.0.0.0
ADMIN_PORT=5000
ADMIN_USERNAME=admin
ADMIN_PASSWORD=secure_admin_password

# Application
DEBUG=False
TIMEZONE=Europe/Moscow

# Commission
COMMISSION_AMOUNT=300
PREPAYMENT_PERCENT=50
```

### Инициализация базы данных

```bash
# Создание миграций
alembic revision --autogenerate -m "Initial migration"

# Применение миграций
alembic upgrade head
```

## 4. Настройка systemd сервисов

### Сервис для бота

Создайте файл `/etc/systemd/system/smena-bot.service`:

```bash
exit  # Выход из пользователя smena
nano /etc/systemd/system/smena-bot.service
```

```ini
[Unit]
Description=SMENA Telegram Bot
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=smena
WorkingDirectory=/home/smena/app
Environment="PATH=/home/smena/app/venv/bin"
ExecStart=/home/smena/app/venv/bin/python /home/smena/app/run_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Сервис для админ-панели

Создайте файл `/etc/systemd/system/smena-admin.service`:

```bash
nano /etc/systemd/system/smena-admin.service
```

```ini
[Unit]
Description=SMENA Admin Panel
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=smena
WorkingDirectory=/home/smena/app
Environment="PATH=/home/smena/app/venv/bin"
ExecStart=/home/smena/app/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 run_admin:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Запуск сервисов

```bash
# Перезагрузка systemd
systemctl daemon-reload

# Включение автозапуска
systemctl enable smena-bot
systemctl enable smena-admin

# Запуск сервисов
systemctl start smena-bot
systemctl start smena-admin

# Проверка статуса
systemctl status smena-bot
systemctl status smena-admin
```

## 5. Настройка Nginx

### Создание конфигурации

```bash
nano /etc/nginx/sites-available/smena
```

```nginx
server {
    listen 80;
    server_name your_domain.com;  # Замените на ваш домен

    # Редирект на HTTPS (настроить после получения SSL)
    # return 301 https://$server_name$request_uri;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /home/smena/app/admin/static;
        expires 30d;
    }

    # Логи
    access_log /var/log/nginx/smena_access.log;
    error_log /var/log/nginx/smena_error.log;
}
```

### Активация конфигурации

```bash
# Создание симлинка
ln -s /etc/nginx/sites-available/smena /etc/nginx/sites-enabled/

# Проверка конфигурации
nginx -t

# Перезапуск Nginx
systemctl restart nginx
```

## 6. Настройка SSL (опционально, но рекомендуется)

### Установка Certbot

```bash
apt install -y certbot python3-certbot-nginx
```

### Получение SSL сертификата

```bash
certbot --nginx -d your_domain.com
```

Следуйте инструкциям certbot для настройки автоматического обновления.

## 7. Настройка firewall

```bash
# Разрешить SSH
ufw allow OpenSSH

# Разрешить HTTP и HTTPS
ufw allow 'Nginx Full'

# Включить firewall
ufw enable
```

## 8. Мониторинг и логи

### Просмотр логов бота

```bash
journalctl -u smena-bot -f
```

### Просмотр логов админ-панели

```bash
journalctl -u smena-admin -f
```

### Просмотр логов Nginx

```bash
tail -f /var/log/nginx/smena_access.log
tail -f /var/log/nginx/smena_error.log
```

### Просмотр логов приложения

```bash
tail -f /home/smena/app/logs/bot.log
tail -f /home/smena/app/logs/admin.log
```

## 9. Обновление проекта

```bash
# Переключение на пользователя smena
su - smena
cd app

# Получение обновлений
git pull origin main

# Активация виртуального окружения
source venv/bin/activate

# Обновление зависимостей
pip install -r requirements.txt

# Применение миграций
alembic upgrade head

# Выход из пользователя
exit

# Перезапуск сервисов
systemctl restart smena-bot
systemctl restart smena-admin
```

## 10. Резервное копирование

### Создание backup скрипта

```bash
nano /home/smena/backup.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/home/smena/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Создание директории для backup
mkdir -p $BACKUP_DIR

# Backup базы данных
pg_dump -U smena_user smena_db | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Удаление старых backup (старше 7 дней)
find $BACKUP_DIR -type f -mtime +7 -delete

echo "Backup completed: $DATE"
```

```bash
chmod +x /home/smena/backup.sh
```

### Настройка cron для автоматического backup

```bash
crontab -e
```

Добавьте строку (backup каждый день в 3:00):

```
0 3 * * * /home/smena/backup.sh >> /home/smena/backup.log 2>&1
```

## Проверка работы

1. **Бот**: отправьте команду `/start` вашему боту в Telegram
2. **Админ-панель**: откройте в браузере `http://your_domain.com` или `http://your_server_ip`
3. **Логи**: проверьте отсутствие ошибок в логах

## Troubleshooting

### Бот не отвечает

```bash
systemctl status smena-bot
journalctl -u smena-bot -n 50
```

### Админ-панель не открывается

```bash
systemctl status smena-admin
systemctl status nginx
journalctl -u smena-admin -n 50
```

### Ошибки базы данных

```bash
# Проверка PostgreSQL
systemctl status postgresql
sudo -u postgres psql -c "\l"
```

## Контакты технической поддержки

По вопросам развертывания обращайтесь к администратору проекта.
