# СМЕНА - Сервис поиска временной работы

Telegram-бот для связи работодателей и людей, ищущих временную подработку.

## Описание

СМЕНА — это сервис-посредник, который:
- Находит исполнителей для временных работ
- Подтверждает выход работников на смену
- Контролирует закрытие заказов
- Управляет комиссиями и платежами

## Технологический стек

- **Backend**: Python 3.10+
- **Framework**: aiogram 3.x (Telegram Bot API)
- **База данных**: PostgreSQL
- **Admin Panel**: Flask + Bootstrap 5
- **ORM**: SQLAlchemy
- **Миграции**: Alembic

## Структура проекта

```
CMENA/
├── bot/                    # Telegram бот
│   ├── handlers/          # Обработчики команд и колбэков
│   ├── keyboards/         # Клавиатуры для бота
│   ├── middlewares/       # Мидлвари
│   ├── states/            # FSM состояния
│   └── utils/             # Утилиты бота
├── admin/                  # Админ-панель
│   ├── routes/            # Маршруты Flask
│   ├── templates/         # HTML шаблоны
│   └── static/            # CSS, JS, изображения
├── database/              # База данных
│   ├── models/            # Модели SQLAlchemy
│   └── migrations/        # Миграции Alembic
├── config/                # Конфигурация
├── services/              # Бизнес-логика
└── requirements.txt       # Зависимости

```

## Установка

### 1. Клонирование и подготовка

```bash
cd CMENA
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Настройка переменных окружения

Создайте файл `.env`:

```env
# Telegram Bot
BOT_TOKEN=your_bot_token_here
ADMIN_IDS=123456789,987654321

# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=smena_db
DB_USER=postgres
DB_PASSWORD=your_password

# Admin Panel
ADMIN_SECRET_KEY=your_secret_key_here
ADMIN_HOST=0.0.0.0
ADMIN_PORT=5000

# Payments (для будущей интеграции)
PAYMENT_TOKEN=your_payment_token

# Application
DEBUG=True
```

### 3. Инициализация базы данных

```bash
# Создание базы данных
alembic init migrations

# Применение миграций
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

### 4. Запуск

```bash
# Запуск бота
python run_bot.py

# Запуск админ-панели (в отдельном терминале)
python run_admin.py
```

## Развертывание на Timeweb VPS

### Подготовка сервера

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# Установка Python и зависимостей
sudo apt install python3.10 python3-pip python3-venv -y

# Установка Nginx
sudo apt install nginx -y
```

### Настройка проекта

```bash
# Клонирование проекта
cd /var/www
git clone <repository_url> smena
cd smena

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Настройка .env файла
nano .env
```

### Настройка systemd для бота

Создайте `/etc/systemd/system/smena-bot.service`:

```ini
[Unit]
Description=SMENA Telegram Bot
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/smena
Environment="PATH=/var/www/smena/venv/bin"
ExecStart=/var/www/smena/venv/bin/python run_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Настройка systemd для админ-панели

Создайте `/etc/systemd/system/smena-admin.service`:

```ini
[Unit]
Description=SMENA Admin Panel
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/smena
Environment="PATH=/var/www/smena/venv/bin"
ExecStart=/var/www/smena/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 run_admin:app
Restart=always

[Install]
WantedBy=multi-user.target
```

### Настройка Nginx

Создайте `/etc/nginx/sites-available/smena`:

```nginx
server {
    listen 80;
    server_name your_domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /static {
        alias /var/www/smena/admin/static;
    }
}
```

Активируйте конфигурацию:

```bash
sudo ln -s /etc/nginx/sites-available/smena /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Запуск сервисов

```bash
sudo systemctl enable smena-bot
sudo systemctl enable smena-admin
sudo systemctl start smena-bot
sudo systemctl start smena-admin
```

## Основные возможности

### Для работодателей
- Регистрация и проверка
- Создание заявок на подбор работников
- Просмотр откликов
- Подтверждение кандидатов
- Оценка работников после смены

### Для работников
- Быстрая регистрация
- Просмотр доступных подработок
- Отклик на вакансии
- Получение уведомлений
- Накопление рейтинга

### Для администратора
- Модерация работодателей и заявок
- Общение с кандидатами
- Контроль предоплат
- Управление статусами заказов
- Блокировка пользователей
- Аналитика и статистика

## Финансовая модель

- Комиссия сервиса: 300 ₽ за успешно закрытую смену
- Предоплата: вносится перед началом смены
- Окончательный расчёт: после завершения смены

## Статусы заказа

1. Создан
2. Модерация
3. Поиск работников
4. Подтверждение кандидатов
5. Предоплата
6. Смена началась
7. Смена завершена
8. Расчёт закрыт

## Безопасность

- Все персональные данные обрабатываются согласно 152-ФЗ
- Требуется юридическое оформление мод��ли посредничества
- Администратор проверяет всех работодателей вручную

## Поддержка

По вопросам и предложениям обращайтесь к администратору проекта.

## Лицензия

Proprietary - все права защищены
