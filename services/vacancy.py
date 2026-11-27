"""
Рассылка вакансии работникам с приоритетом для надёжных.

Этапы:
  • "first" — сразу после одобрения заказа: приоритетные работники
    (см. services.reliability.is_priority). Если приоритетных нет или задержка 0,
    вакансия сразу уходит всем;
  • "rest" — остальным подходящим работникам через PRIORITY_DELAY_MINUTES
    (запускает планировщик бота). Сюда же попадают те, кто зарегистрировался позже.

Кому уже отправлено, хранится в order_events (kind="vacancy_sent"), поэтому
повторов не бывает. Работники с большим числом штрафных баллов вакансии не получают.
Модуль без ввода-вывода: бот и админка сами читают БД и отправляют сообщения.
"""
from config import PRIORITY_DELAY_MINUTES
from services import reliability as R
from services import order_texts as T

EV_PRIORITY = "broadcast_priority"   # первый этап выполнен (новая схема рассылки)
EV_REST = "broadcast_rest"           # второй этап выполнен
EV_SENT = "vacancy_sent"             # конкретному работнику (user_id)


def plan(order, workers, points: dict, *, responded_worker_ids=(), sent_user_ids=(),
         stage: str = "first", delay_minutes: int = None):
    """Вернуть (targets, priority_ids, order_events) — кому слать и какие события записать"""
    delay = PRIORITY_DELAY_MINUTES if delay_minutes is None else delay_minutes
    responded, sent = set(responded_worker_ids), set(sent_user_ids)
    candidates = [w for w in workers if R.matches_order(w, order)
                  and w.id not in responded and w.user_id not in sent]
    priority, rest, _restricted = R.split_recipients(candidates, points)
    priority_ids = {w.id for w in priority}
    if stage == "first":
        if delay > 0 and priority:
            return priority, priority_ids, [EV_PRIORITY]
        return priority + rest, priority_ids, [EV_PRIORITY, EV_REST]
    return priority + rest, priority_ids, [EV_REST]


def vacancy_text(order, priority: bool = False) -> str:
    text = f"🆕 <b>Новая вакансия #{order.id}</b>\n\n{T.order_details(order)}"
    if priority:
        text += ("\n\n⚡️ <i>Вы получили вакансию раньше других как надёжный работник. "
                 "Откликайтесь, пока есть места!</i>")
    return text


def vacancy_rows(order_id: int):
    return [[("✅ Откликнуться", f"respond:{order_id}")]]
