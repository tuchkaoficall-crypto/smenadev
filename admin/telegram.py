"""
Синхронная отправка уведомлений в Telegram из веб-админки.

Админка работает на Flask (синхронно), поэтому async-бот aiogram здесь
не используется — шлём запросы напрямую в Bot API.
"""
import json
import logging
import urllib.parse
import urllib.request

from config import BOT_TOKEN

logger = logging.getLogger(__name__)


def send_message(chat_id: int, text: str, reply_markup: dict = None, parse_mode: str = None) -> bool:
    """Отправить сообщение пользователю. Ошибки логируются, но не пробрасываются."""
    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN не задан, уведомление не отправлено")
        return False

    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200
    except Exception as e:
        logger.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
        return False


def notify_workers_new_order(db_session, order) -> int:
    """Первый этап рассылки вакансии (как в боте, см. services/vacancy.py): надёжным сразу,
    остальным через PRIORITY_DELAY_MINUTES отправит планировщик бота. Возвращает число отправленных."""
    from datetime import datetime
    from database.models import Worker, Response, OrderEvent
    from config import OrderStatus
    from services import vacancy as V
    from services import reliability as R
    from services import order_keyboards as K

    if order.status != OrderStatus.SEARCH_WORKERS or order.shift_date <= datetime.now():
        return 0
    done = {k for (k,) in db_session.query(OrderEvent.kind).filter(
        OrderEvent.order_id == order.id, OrderEvent.user_id == 0,
        OrderEvent.kind.in_((V.EV_PRIORITY, V.EV_REST)))}
    if V.EV_PRIORITY in done:
        return 0
    workers = db_session.query(Worker).filter(Worker.city == order.city).all()
    responded = {wid for (wid,) in db_session.query(Response.worker_id).filter(Response.order_id == order.id)}
    sent_ids = {uid for (uid,) in db_session.query(OrderEvent.user_id).filter(
        OrderEvent.order_id == order.id, OrderEvent.kind == V.EV_SENT)}
    points = R.points_map_sync(db_session, [w.id for w in workers])
    targets, priority_ids, events = V.plan(order, workers, points, responded_worker_ids=responded,
                                           sent_user_ids=sent_ids, stage="first")
    for kind in events:
        if kind not in done:
            db_session.add(OrderEvent(order_id=order.id, kind=kind, user_id=0))
    for w in targets:
        db_session.add(OrderEvent(order_id=order.id, kind=V.EV_SENT, user_id=w.user_id))
    db_session.commit()

    sent = 0
    markup = K.to_dict(V.vacancy_rows(order.id))
    for w in targets:
        if send_message(w.user_id, V.vacancy_text(order, w.id in priority_ids), markup, parse_mode="HTML"):
            sent += 1
    return sent


def get_file(file_id: str):
    """Скачать файл из Telegram (для просмотра документов в панели): (bytes, путь) или (None, None)"""
    if not BOT_TOKEN or not file_id:
        return None, None
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={urllib.parse.quote(file_id)}"
        with urllib.request.urlopen(url, timeout=10) as r:
            info = json.loads(r.read().decode("utf-8"))
        path = info.get("result", {}).get("file_path")
        if not path:
            return None, None
        with urllib.request.urlopen(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}", timeout=20) as r:
            return r.read(), path
    except Exception as e:
        logger.warning("Не удалось получить файл из Telegram: %s", e)
        return None, None
