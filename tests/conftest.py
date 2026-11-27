"""
Общие фикстуры тестов.

Тесты НЕ трогают рабочую базу и Telegram:
  • SQLITE_PATH указывает на временный файл (новая схема перед каждым тестом);
  • BOT_TOKEN фиктивный, все запросы бота перехватывает FakeSession;
  • веб-админка шлёт сообщения через admin.telegram.send_message — он подменён.
Переменные окружения задаются до импорта проекта; dotenv их не перезаписывает.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smena_tests_")
os.environ.update({
    "USE_SQLITE": "True",
    "SQLITE_PATH": os.path.join(_TMP, "test.sqlite"),
    "BOT_TOKEN": "123456:TEST-TOKEN-FOR-PYTEST",
    "ADMIN_IDS": "999",
    "ADMIN_USERNAME": "tester",
    "ADMIN_PASSWORD": "tester-pass",
    "ADMIN_SECRET_KEY": "tests",
    "PRIORITY_DELAY_MINUTES": "15",
    "REFERRAL_BONUS": "300",
})

import pytest  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import SendMessage, GetMe, GetChatMember, EditMessageText  # noqa: E402
from aiogram.types import Message, Chat, User as TgUser, ChatMemberMember, Update  # noqa: E402

ADMIN_ID = 999


class FakeSession(BaseSession):
    """Сессия aiogram без сети: запоминает запросы и отвечает правдоподобными объектами"""

    def __init__(self):
        super().__init__()
        self.requests = []
        self._mid = 100

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, GetMe):
            return TgUser(id=123456, is_bot=True, first_name="Смена", username="smena_test_bot")
        if isinstance(method, GetChatMember):
            return ChatMemberMember(user=TgUser(id=method.user_id, is_bot=False, first_name="U"))
        if isinstance(method, (SendMessage, EditMessageText)):
            self._mid += 1
            chat_id = getattr(method, "chat_id", 0) or 0
            return Message(message_id=self._mid, date=datetime.now(),
                           chat=Chat(id=int(chat_id), type="private"), text=getattr(method, "text", ""))
        return True

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    async def close(self):
        pass


class Outbox:
    """Удобный доступ к отправленным сообщениям (бот + веб-админка)"""

    def __init__(self, session: FakeSession):
        self.session = session
        self.admin = []  # (chat_id, text, markup)

    @property
    def messages(self):
        bot_msgs = [(int(m.chat_id), m.text, m.reply_markup) for m in self.session.requests
                    if isinstance(m, SendMessage)]
        return bot_msgs + self.admin

    def to(self, chat_id):
        return [t for c, t, _ in self.messages if c == chat_id]

    def buttons_to(self, chat_id):
        out = []
        for c, _, markup in self.messages:
            if c != chat_id or not markup:
                continue
            rows = markup["inline_keyboard"] if isinstance(markup, dict) else getattr(markup, "inline_keyboard", [])
            for row in rows or []:
                for b in row:
                    out.append(b["callback_data"] if isinstance(b, dict) else b.callback_data)
        return out

    def answers(self):
        """Ответы на callback (всплывающие)"""
        from aiogram.methods import AnswerCallbackQuery
        return [m.text for m in self.session.requests if isinstance(m, AnswerCallbackQuery)]

    def clear(self):
        self.session.requests.clear()
        self.admin.clear()


@pytest.fixture(scope="session")
def fake_session():
    from bot.bot_instance import bot
    s = FakeSession()
    bot.session = s
    return s


@pytest.fixture(scope="session")
def dp():
    from bot.dispatcher import build_dispatcher
    return build_dispatcher()


@pytest.fixture(autouse=True)
async def db(fake_session, monkeypatch):
    """Чистая база перед каждым тестом"""
    from database.database import engine, Base
    from database.migrate import upgrade_schema
    import database.models  # noqa: F401
    from services import cities
    from bot.utils import referrals
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(upgrade_schema)
    cities.set_cache([])
    referrals._bot_username = None
    fake_session.requests.clear()
    yield
    await engine.dispose()


@pytest.fixture
def outbox(fake_session, monkeypatch):
    box = Outbox(fake_session)
    try:
        from admin import telegram

        def fake_send(chat_id, text, reply_markup=None, parse_mode=None):
            box.admin.append((int(chat_id), text, reply_markup))
            return True
        monkeypatch.setattr(telegram, "send_message", fake_send)
    except Exception:
        pass
    return box


# ==== Фабрики данных ====

async def make_user(session, uid, role, name="Иван Петров", phone="+79001234567", blocked=False):
    from database.models import User
    first, _, last = name.partition(" ")
    u = User(id=uid, first_name=first, last_name=last or None, role=role, phone=phone, is_blocked=blocked)
    session.add(u)
    await session.flush()
    return u


async def make_employer(session, uid=1000, status="approved"):
    from database.models import Employer
    await make_user(session, uid, "employer", "Анна Смирнова")
    e = Employer(user_id=uid, company_name="ООО Склад", contact_person="Анна", contact_phone="+79000000000",
                 status=status)
    session.add(e)
    await session.commit()
    return e


async def make_worker(session, uid, city="Петрозаводск", categories=(), **fields):
    import json
    from database.models import Worker
    await make_user(session, uid, "worker", fields.pop("name", f"Работник {uid}"),
                    blocked=fields.pop("blocked", False))
    w = Worker(user_id=uid, city=city, categories=json.dumps(list(categories), ensure_ascii=False), **fields)
    session.add(w)
    await session.commit()
    return w


async def make_order(session, employer, *, hours_ahead=48, status="search_workers", workers_needed=2,
                     city="Петрозаводск", category="Грузчик", duration=8, **fields):
    from database.models import Order
    o = Order(employer_id=employer.id, city=city, address="ул. Ленина, 1", category=category,
              shift_date=datetime.now().replace(second=0, microsecond=0) + timedelta(hours=hours_ahead),
              shift_duration=duration, workers_needed=workers_needed, description="Разгрузка",
              payment_type="per_shift", payment_amount=3000, commission=600, prepayment_amount=300,
              status=status, moderated_at=fields.pop("moderated_at", datetime.utcnow()), **fields)
    session.add(o)
    await session.commit()
    return o


async def make_response(session, order, worker, status="pending"):
    from database.models import Response
    r = Response(order_id=order.id, worker_id=worker.id, status=status,
                 confirmed_at=datetime.utcnow() if status == "confirmed" else None)
    session.add(r)
    await session.commit()
    return r


# ==== Апдейты Telegram для проверки обработчиков бота ====

_uid = [1]


def _next_id():
    _uid[0] += 1
    return _uid[0]


def _from(user_id):
    return {"id": user_id, "is_bot": False, "first_name": "Тест", "username": f"user{user_id}"}


def message_update(user_id, text=None, **extra):
    msg = {"message_id": _next_id(), "date": int(datetime.now().timestamp()),
           "chat": {"id": user_id, "type": "private"}, "from": _from(user_id)}
    if text is not None:
        msg["text"] = text
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    msg.update(extra)
    return Update.model_validate({"update_id": _next_id(), "message": msg})


def callback_update(user_id, data):
    msg = {"message_id": _next_id(), "date": int(datetime.now().timestamp()),
           "chat": {"id": user_id, "type": "private"}, "from": {"id": 123456, "is_bot": True, "first_name": "Bot"},
           "text": "кнопки"}
    return Update.model_validate({"update_id": _next_id(), "callback_query": {
        "id": str(_next_id()), "from": _from(user_id), "chat_instance": "ci", "data": data, "message": msg}})


async def feed(dp, update):
    from bot.bot_instance import bot
    await dp.feed_update(bot, update)
